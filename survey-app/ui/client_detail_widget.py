"""Client detail dialog — info, specialists, survey history."""
import logging
from datetime import date

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout,
    QGroupBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy import nullslast
from sqlalchemy.orm import Session

from models import Client, ClientStatus, Employee, Satisfaction, SituationStatus, Survey

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


def _ro_item(text: str, bg: QColor | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if bg:
        item.setBackground(bg)
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
        date_row = QWidget()
        date_row_l = QHBoxLayout(date_row)
        date_row_l.setContentsMargins(0, 0, 0, 0)
        date_row_l.addWidget(self._start_date_check)
        date_row_l.addWidget(self._start_date_edit)
        date_row_l.addStretch()
        info_f.addRow("Дата начала:", date_row)

        self._status_cb = QComboBox()
        for st in ClientStatus:
            self._status_cb.addItem(st.value, st)
        info_f.addRow("Статус:", self._status_cb)

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
        survey_bar.addWidget(add_survey_btn)
        survey_bar.addWidget(self._edit_survey_btn)
        survey_bar.addStretch()
        surveys_l.addLayout(survey_bar)

        self._survey_table = QTableWidget(0, 5)
        self._survey_table.setHorizontalHeaderLabels(
            ["Тип", "Дата", "Удовлетворённость", "Недопон.", "Статус ситуации"]
        )
        hh = self._survey_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
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
        _set_combo(self._status_cb, c.status)
        self._load_specialists()
        self._load_surveys()

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

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_survey_sel(self) -> None:
        has = bool(self._survey_table.selectionModel().selectedRows())
        self._edit_survey_btn.setEnabled(has)

    def _selected_survey(self) -> Survey | None:
        rows = self._survey_table.selectionModel().selectedRows()
        return self._surveys[rows[0].row()] if rows else None

    def _save_client_info(self) -> None:
        name = self._child_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "ФИО ребёнка не может быть пустым.")
            return
        try:
            self._client.child_name = name
            self._client.parent_name = self._parent_name_edit.text().strip() or None
            if self._start_date_check.isChecked():
                qd = self._start_date_edit.date()
                self._client.start_date = date(qd.year(), qd.month(), qd.day())
            else:
                self._client.start_date = None
            self._client.status = self._status_cb.currentData()
            self._session.commit()
            log.info("Client id=%s info saved", self._client.id)
            self.client_updated.emit()
            QMessageBox.information(self, "Сохранено", "Данные клиента обновлены.")
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to save client info")
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
