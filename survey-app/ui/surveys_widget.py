"""All-surveys table with filters."""
import logging
from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from sqlalchemy import nullslast
from sqlalchemy.orm import Session

from models import Client, ContactType, Misunderstanding, Satisfaction, SituationStatus, Survey
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


class SurveysWidget(QWidget):
    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session = session
        self._surveys: list[Survey] = []
        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Filter row 1: type, situation_status, satisfaction
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Тип:"))
        self._type_filter = QComboBox()
        self._type_filter.addItem("Все", None)
        for ct in ContactType:
            self._type_filter.addItem(ct.value, ct)
        row1.addWidget(self._type_filter)

        row1.addWidget(QLabel("Ситуация:"))
        self._sit_filter = QComboBox()
        self._sit_filter.addItem("Все", None)
        for st in SituationStatus:
            self._sit_filter.addItem(st.value, st)
        row1.addWidget(self._sit_filter)

        row1.addWidget(QLabel("Удовлетв.:"))
        self._sat_filter = QComboBox()
        self._sat_filter.addItem("Все", None)
        for sat in Satisfaction:
            self._sat_filter.addItem(sat.value, sat)
        row1.addWidget(self._sat_filter)
        row1.addStretch()
        root.addLayout(row1)

        # Filter row 2: date range + apply
        row2 = QHBoxLayout()
        self._from_check = QCheckBox("С:")
        self._from_date = QDateEdit(QDate(2020, 1, 1))
        self._from_date.setCalendarPopup(True)
        self._from_date.setDisplayFormat("dd.MM.yyyy")
        self._from_date.setEnabled(False)
        self._from_check.toggled.connect(self._from_date.setEnabled)

        self._to_check = QCheckBox("По:")
        self._to_date = QDateEdit(QDate.currentDate())
        self._to_date.setCalendarPopup(True)
        self._to_date.setDisplayFormat("dd.MM.yyyy")
        self._to_date.setEnabled(False)
        self._to_check.toggled.connect(self._to_date.setEnabled)

        apply_btn = QPushButton("Применить фильтр")
        apply_btn.clicked.connect(self.load_data)

        row2.addWidget(self._from_check)
        row2.addWidget(self._from_date)
        row2.addWidget(self._to_check)
        row2.addWidget(self._to_date)
        row2.addWidget(apply_btn)
        row2.addStretch()
        root.addLayout(row2)

        # Table
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Клиент", "Тип", "Дата", "Удовлетворённость", "Недопон.", "Статус ситуации"]
        )
        setup_resizable_columns(
            self._table, "surveys",
            [210, 110, 90, 130, 80, 160],
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_sel)
        self._table.doubleClicked.connect(self._edit_survey)
        root.addWidget(self._table)

        # Toolbar
        btn_bar = QHBoxLayout()
        self._edit_btn = QPushButton("Редактировать опрос")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._edit_survey)
        self._del_btn = QPushButton("Удалить опрос")
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._delete_survey)
        btn_bar.addWidget(self._edit_btn)
        btn_bar.addWidget(self._del_btn)
        btn_bar.addStretch()
        root.addLayout(btn_bar)

    # ------------------------------------------------------------------
    def load_data(self) -> None:
        q = (
            self._session.query(Survey)
            .join(Survey.client)
            .order_by(Client.child_name, nullslast(Survey.contact_date.asc()))
        )

        ct_filter = self._type_filter.currentData()
        if ct_filter:
            q = q.filter(Survey.contact_type == ct_filter)

        sit_filter = self._sit_filter.currentData()
        if sit_filter:
            q = q.filter(Survey.situation_status == sit_filter)

        sat_filter = self._sat_filter.currentData()
        if sat_filter:
            q = q.filter(Survey.satisfaction == sat_filter)

        if self._from_check.isChecked():
            qd = self._from_date.date()
            q = q.filter(Survey.contact_date >= date(qd.year(), qd.month(), qd.day()))

        if self._to_check.isChecked():
            qd = self._to_date.date()
            q = q.filter(Survey.contact_date <= date(qd.year(), qd.month(), qd.day()))

        self._surveys = q.all()
        self._table.setRowCount(len(self._surveys))

        for row, s in enumerate(self._surveys):
            client_name = s.client.child_name if s.client else "—"
            ct  = s.contact_type.value if s.contact_type else "—"
            dt  = s.contact_date.strftime("%d.%m.%Y") if s.contact_date else "—"
            sat = s.satisfaction.value if s.satisfaction else "—"
            mis = "Да" if s.misunderstanding and s.misunderstanding.value == "Да" else "Нет"
            sit = s.situation_status.value if s.situation_status else "—"
            row_bg = _STATUS_BG.get(s.situation_status)
            for col, val in enumerate([client_name, ct, dt, sat, mis, sit]):
                item = _ro_item(val, row_bg)
                if col == 3 and s.satisfaction:
                    item.setBackground(_SAT_BG.get(s.satisfaction, row_bg))
                self._table.setItem(row, col, item)

        self._edit_btn.setEnabled(False)
        self._del_btn.setEnabled(False)

    # ------------------------------------------------------------------
    def _on_sel(self) -> None:
        has = bool(self._table.selectionModel().selectedRows())
        self._edit_btn.setEnabled(has)
        self._del_btn.setEnabled(has)

    def _selected_survey(self) -> Survey | None:
        rows = self._table.selectionModel().selectedRows()
        return self._surveys[rows[0].row()] if rows else None

    def _delete_survey(self) -> None:
        s = self._selected_survey()
        if s is None:
            return
        client_name = s.client.child_name if s.client else "—"
        dt = s.contact_date.strftime("%d.%m.%Y") if s.contact_date else "без даты"
        ct = s.contact_type.value if s.contact_type else "без типа"
        msg = (
            f"Удалить опрос «{ct}» от {dt}\n"
            f"клиента «{client_name}»?\n\n"
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
            log.info("Deleted survey id=%s", s.id)
            self.load_data()
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to delete survey")
            QMessageBox.critical(self, "Ошибка", str(exc))

    def _edit_survey(self) -> None:
        s = self._selected_survey()
        if s is None:
            return
        from ui.survey_form_widget import SurveyFormDialog
        dlg = SurveyFormDialog(self._session, s.client_id, survey=s, parent=self)
        dlg.survey_saved.connect(self.load_data)
        dlg.exec()
