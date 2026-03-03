"""Client detail dialog — info, specialists, survey history."""
import logging
from datetime import date

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout,
    QGroupBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy import nullslast
from sqlalchemy.orm import Session

from models import Client, ClientStatus, Employee, FeedbackStatus, Satisfaction, SituationStatus, Survey
from ui.table_utils import setup_resizable_columns

log = logging.getLogger(__name__)

_STATUS_BG = {
    SituationStatus.IN_PROGRESS: QColor("#FFF3CD"),
    SituationStatus.RESOLVED:    QColor("#D4EDDA"),
    SituationStatus.UNRESOLVED:  QColor("#F8D7DA"),
    SituationStatus.CLOSED:      QColor("#E2E3E5"),
}
_SAT_BG = {
    Satisfaction.SATISFIED:   QColor("#D4EDDA"),
    Satisfaction.UNSATISFIED: QColor("#F8D7DA"),
}


_DARK_TEXT = QColor("#212529")


def _ro_item(text: str, bg: QColor | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if bg:
        item.setBackground(bg)
        item.setForeground(_DARK_TEXT)   # readable in both light & dark themes
    return item


def _set_combo(cb: QComboBox, value) -> None:
    for i in range(cb.count()):
        if cb.itemData(i) == value:
            cb.setCurrentIndex(i)
            return


class ClientDetailDialog(QDialog):
    """Detailed view of a single client: info, specialists, surveys."""

    client_updated = pyqtSignal()

    def __init__(self, session: Session, client: Client, parent=None):
        super().__init__(parent)
        self._session = session
        self._client = client
        self._specialist_checks: list[tuple[Employee, QCheckBox]] = []
        self._surveys: list[Survey] = []
        self._build_ui()
        self._populate()
        self.setWindowTitle(f"Карточка клиента — {client.child_name}")
        self.setMinimumSize(700, 580)
        self.resize(820, 700)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_l = QVBoxLayout(inner)
        inner_l.setSpacing(10)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        # ── Client info ──────────────────────────────────────────────
        info_g = QGroupBox("Информация о клиенте")
        info_f = QFormLayout(info_g)

        self._child_name_edit = QLineEdit()
        info_f.addRow("ФИО ребёнка:", self._child_name_edit)

        self._parent_name_edit = QLineEdit()
        self._parent_name_edit.setPlaceholderText("необязательно")
        info_f.addRow("ФИО родителя:", self._parent_name_edit)

        self._start_date_check = QCheckBox("Указать дату")
        self._start_date_edit = QDateEdit(QDate.currentDate())
        self._start_date_edit.setCalendarPopup(True)
        self._start_date_edit.setDisplayFormat("dd.MM.yyyy")
        self._start_date_edit.setEnabled(False)
        self._start_date_check.toggled.connect(self._start_date_edit.setEnabled)
        self._start_date_edit.dateChanged.connect(self._update_duration_label)
        start_row = QWidget()
        start_row_l = QHBoxLayout(start_row)
        start_row_l.setContentsMargins(0, 0, 0, 0)
        start_row_l.addWidget(self._start_date_check)
        start_row_l.addWidget(self._start_date_edit)
        start_row_l.addStretch()
        info_f.addRow("Дата начала:", start_row)

        # ── Дата окончания ────────────────────────────────────────────
        self._end_date_check = QCheckBox("Указать дату")
        self._end_date_edit = QDateEdit(QDate.currentDate())
        self._end_date_edit.setCalendarPopup(True)
        self._end_date_edit.setDisplayFormat("dd.MM.yyyy")
        self._end_date_edit.setEnabled(False)
        self._end_date_check.toggled.connect(self._end_date_edit.setEnabled)
        self._end_date_check.toggled.connect(self._update_duration_label)
        self._end_date_edit.dateChanged.connect(self._update_duration_label)
        end_row = QWidget()
        end_row_l = QHBoxLayout(end_row)
        end_row_l.setContentsMargins(0, 0, 0, 0)
        end_row_l.addWidget(self._end_date_check)
        end_row_l.addWidget(self._end_date_edit)
        end_row_l.addStretch()
        info_f.addRow("Дата окончания:", end_row)

        # ── Продолжительность (read-only label) ───────────────────────
        self._duration_lbl = QLabel("—")
        self._duration_lbl.setStyleSheet("color: #6c757d; font-style: italic;")
        info_f.addRow("Продолжительность:", self._duration_lbl)

        self._status_cb = QComboBox()
        for st in ClientStatus:
            self._status_cb.addItem(st.value, st)
        info_f.addRow("Статус:", self._status_cb)

        # ── Статус обратной связи ─────────────────────────────────────
        self._feedback_cb = QComboBox()
        self._feedback_cb.addItem("—", None)
        for fs in FeedbackStatus:
            self._feedback_cb.addItem(fs.value, fs)
        info_f.addRow("Статус обратной связи:", self._feedback_cb)

        # ── Примечания ────────────────────────────────────────────────
        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setPlaceholderText("Дополнительные заметки…")
        self._notes_edit.setFixedHeight(80)
        info_f.addRow("Примечания:", self._notes_edit)

        save_btn = QPushButton("Сохранить изменения")
        save_btn.clicked.connect(self._save_client_info)
        info_f.addRow("", save_btn)

        inner_l.addWidget(info_g)

        # ── Specialists ───────────────────────────────────────────────
        self._spec_g = QGroupBox("Специалисты")
        self._spec_grid = QGridLayout(self._spec_g)
        inner_l.addWidget(self._spec_g)

        # ── Surveys ───────────────────────────────────────────────────
        surveys_g = QGroupBox("История опросов")
        surveys_l = QVBoxLayout(surveys_g)

        survey_bar = QHBoxLayout()
        add_survey_btn = QPushButton("Добавить опрос")
        add_survey_btn.clicked.connect(self._add_survey)
        self._edit_survey_btn = QPushButton("Редактировать")
        self._edit_survey_btn.setEnabled(False)
        self._edit_survey_btn.clicked.connect(self._edit_survey)
        self._del_survey_btn = QPushButton("Удалить опрос")
        self._del_survey_btn.setEnabled(False)
        self._del_survey_btn.clicked.connect(self._delete_survey)
        survey_bar.addWidget(add_survey_btn)
        survey_bar.addWidget(self._edit_survey_btn)
        survey_bar.addWidget(self._del_survey_btn)
        survey_bar.addStretch()
        surveys_l.addLayout(survey_bar)

        self._survey_table = QTableWidget(0, 5)
        self._survey_table.setHorizontalHeaderLabels(
            ["Тип", "Дата", "Удовлетворённость", "Недопон.", "Статус ситуации"]
        )
        setup_resizable_columns(
            self._survey_table, "client_surveys",
            [110, 90, 130, 80, 180],
        )
        self._survey_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._survey_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._survey_table.setMinimumHeight(200)
        self._survey_table.itemSelectionChanged.connect(self._on_survey_sel)
        self._survey_table.doubleClicked.connect(self._edit_survey)
        surveys_l.addWidget(self._survey_table)

        inner_l.addWidget(surveys_g)

        # ── Close ─────────────────────────────────────────────────────
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn)

    # ------------------------------------------------------------------
    # Populate
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        c = self._client
        self._child_name_edit.setText(c.child_name)
        self._parent_name_edit.setText(c.parent_name or "")
        if c.start_date:
            self._start_date_check.setChecked(True)
            self._start_date_edit.setDate(
                QDate(c.start_date.year, c.start_date.month, c.start_date.day)
            )
        if c.end_date:
            self._end_date_check.setChecked(True)
            self._end_date_edit.setDate(
                QDate(c.end_date.year, c.end_date.month, c.end_date.day)
            )
        _set_combo(self._status_cb, c.status)
        _set_combo(self._feedback_cb, c.feedback_status)
        self._notes_edit.setPlainText(c.notes or "")
        self._update_duration_label()
        self._load_specialists()
        self._load_surveys()

    def _update_duration_label(self) -> None:
        """Recalculate and display duration from current widget values."""
        if not (self._start_date_check.isChecked() and self._end_date_check.isChecked()):
            self._duration_lbl.setText("—")
            return
        qsd = self._start_date_edit.date()
        qed = self._end_date_edit.date()
        start = date(qsd.year(), qsd.month(), qsd.day())
        end   = date(qed.year(), qed.month(), qed.day())
        if end < start:
            self._duration_lbl.setText("⚠ Дата окончания раньше даты начала")
            self._duration_lbl.setStyleSheet("color: #dc3545; font-style: italic;")
            return
        from calendar import monthrange
        y1, m1, d1 = start.year, start.month, start.day
        y2, m2, d2 = end.year,   end.month,   end.day
        months = (y2 - y1) * 12 + (m2 - m1)
        if d2 < d1:
            months -= 1
            prev_m = m2 - 1 if m2 > 1 else 12
            prev_y = y2 if m2 > 1 else y2 - 1
            prev_last = monthrange(prev_y, prev_m)[1]
            days = (prev_last - d1) + d2 + 1
        else:
            days = d2 - d1
        parts = []
        if months:
            parts.append(f"{months} мес")
        if days:
            parts.append(f"{days} дн")
        text = " ".join(parts) or "0 дн"
        self._duration_lbl.setText(text)
        self._duration_lbl.setStyleSheet("color: #6c757d; font-style: italic;")

    def _load_specialists(self) -> None:
        while self._spec_grid.count():
            item = self._spec_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._specialist_checks.clear()

        employees = (
            self._session.query(Employee)
            .order_by(Employee.full_name)
            .all()
        )
        if not employees:
            self._spec_grid.addWidget(QLabel("Нет сотрудников в системе"), 0, 0)
            return

        assigned_ids = {e.id for e in self._client.specialists}
        for idx, emp in enumerate(employees):
            cb = QCheckBox(f"{emp.full_name} ({emp.positions_display})")
            cb.setChecked(emp.id in assigned_ids)
            cb.toggled.connect(
                lambda checked, e=emp: self._on_specialist_toggled(e, checked)
            )
            self._spec_grid.addWidget(cb, idx // 2, idx % 2)
            self._specialist_checks.append((emp, cb))

    def _on_specialist_toggled(self, employee: Employee, checked: bool) -> None:
        try:
            if checked and employee not in self._client.specialists:
                self._client.specialists.append(employee)
            elif not checked and employee in self._client.specialists:
                self._client.specialists.remove(employee)
            self._session.commit()
            log.debug(
                "Specialist %r %s client %r",
                employee.full_name,
                "added to" if checked else "removed from",
                self._client.child_name,
            )
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to update specialist link")
            QMessageBox.critical(self, "Ошибка", str(exc))

    def _load_surveys(self) -> None:
        self._surveys = (
            self._session.query(Survey)
            .filter(Survey.client_id == self._client.id)
            .order_by(nullslast(Survey.contact_date.asc()))
            .all()
        )
        self._survey_table.setRowCount(len(self._surveys))
        for row, s in enumerate(self._surveys):
            ct  = s.contact_type.value if s.contact_type else "—"
            dt  = s.contact_date.strftime("%d.%m.%Y") if s.contact_date else "—"
            sat = s.satisfaction.value if s.satisfaction else "—"
            mis = "Да" if s.misunderstanding and s.misunderstanding.value == "Да" else "Нет"
            sit = s.situation_status.value if s.situation_status else "—"
            row_bg = _STATUS_BG.get(s.situation_status)
            for col, val in enumerate([ct, dt, sat, mis, sit]):
                item = _ro_item(val, row_bg)
                if col == 2 and s.satisfaction:
                    item.setBackground(_SAT_BG.get(s.satisfaction, row_bg))
                self._survey_table.setItem(row, col, item)
        self._edit_survey_btn.setEnabled(False)
        self._del_survey_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_survey_sel(self) -> None:
        has = bool(self._survey_table.selectionModel().selectedRows())
        self._edit_survey_btn.setEnabled(has)
        self._del_survey_btn.setEnabled(has)

    def _selected_survey(self) -> Survey | None:
        rows = self._survey_table.selectionModel().selectedRows()
        return self._surveys[rows[0].row()] if rows else None

    def _save_client_info(self) -> None:
        name = self._child_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "ФИО ребёнка не может быть пустым.")
            return

        start_date = None
        if self._start_date_check.isChecked():
            qd = self._start_date_edit.date()
            start_date = date(qd.year(), qd.month(), qd.day())

        end_date = None
        if self._end_date_check.isChecked():
            qd = self._end_date_edit.date()
            end_date = date(qd.year(), qd.month(), qd.day())

        if start_date and end_date and end_date < start_date:
            QMessageBox.warning(
                self, "Ошибка",
                "Дата окончания не может быть раньше даты начала."
            )
            return

        try:
            self._client.child_name   = name
            self._client.parent_name  = self._parent_name_edit.text().strip() or None
            self._client.start_date   = start_date
            self._client.end_date     = end_date
            self._client.status       = self._status_cb.currentData()
            self._client.feedback_status = self._feedback_cb.currentData()
            self._client.notes        = self._notes_edit.toPlainText().strip() or None
            self._session.commit()
            log.info("Client id=%s info saved", self._client.id)
            self.client_updated.emit()
            QMessageBox.information(self, "Сохранено", "Данные клиента обновлены.")
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to save client info")
            QMessageBox.critical(self, "Ошибка", str(exc))

    def _delete_survey(self) -> None:
        s = self._selected_survey()
        if s is None:
            return
        dt = s.contact_date.strftime("%d.%m.%Y") if s.contact_date else "без даты"
        ct = s.contact_type.value if s.contact_type else "без типа"
        msg = (
            f"Удалить опрос «{ct}» от {dt}?\n\n"
            "Это действие нельзя отменить."
        )
        reply = QMessageBox.warning(
            self, "Подтверждение удаления", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._session.delete(s)
            self._session.commit()
            log.info("Deleted survey id=%s from client id=%s", s.id, self._client.id)
            self._load_surveys()
            self.client_updated.emit()
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to delete survey")
            QMessageBox.critical(self, "Ошибка", str(exc))

    def _add_survey(self) -> None:
        from ui.survey_form_widget import SurveyFormDialog
        dlg = SurveyFormDialog(self._session, self._client.id, parent=self)
        dlg.survey_saved.connect(self._load_surveys)
        dlg.exec()

    def _edit_survey(self) -> None:
        s = self._selected_survey()
        if s is None:
            return
        from ui.survey_form_widget import SurveyFormDialog
        dlg = SurveyFormDialog(self._session, self._client.id, survey=s, parent=self)
        dlg.survey_saved.connect(self._load_surveys)
        dlg.exec()
