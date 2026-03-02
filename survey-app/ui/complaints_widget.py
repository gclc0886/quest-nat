"""
Complaints / situations tab.

Shows all surveys that triggered a complaint situation
(complaint_employee, complaint_conditions, unsatisfied, misunderstanding).
Mirrors the Employees tab structure: toolbar + filter + table.
"""
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import (
    Client, ClientStatus, Misunderstanding, Satisfaction,
    SituationStatus, Survey,
)

log = logging.getLogger(__name__)

# ── Colour coding ────────────────────────────────────────────────────────────
_STATUS_FG = {
    SituationStatus.IN_PROGRESS: QColor("#856404"),   # amber text
    SituationStatus.RESOLVED:    QColor("#155724"),   # green text
    SituationStatus.UNRESOLVED:  QColor("#721c24"),   # red text
    SituationStatus.CLOSED:      QColor("#6c757d"),   # gray text
}
_STATUS_BG = {
    SituationStatus.IN_PROGRESS: QColor("#FFF3CD"),
    SituationStatus.RESOLVED:    QColor("#D4EDDA"),
    SituationStatus.UNRESOLVED:  QColor("#F8D7DA"),
    SituationStatus.CLOSED:      QColor("#E2E3E5"),
}


def _ro_item(text: str,
             fg: QColor | None = None,
             bg: QColor | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if fg:
        item.setForeground(fg)
    if bg:
        item.setBackground(bg)
    return item


def _complaint_type(survey: Survey) -> str:
    """Human-readable complaint type label."""
    has_emp  = survey.complaint_employee
    has_cond = survey.complaint_conditions
    if has_emp and has_cond:
        return "Сотрудник + Условия"
    if has_emp:
        return "На сотрудника"
    if has_cond:
        return "На условия"
    # Reached here from satisfaction/misunderstanding only
    parts = []
    if survey.satisfaction == Satisfaction.UNSATISFIED:
        parts.append("Недовольство")
    if survey.misunderstanding == Misunderstanding.YES:
        parts.append("Недопонимание")
    return " / ".join(parts) if parts else "—"


def _complaint_detail(survey: Survey) -> str:
    """Short text excerpt for the Detail column."""
    parts = []
    if survey.complaint_employee_text:
        parts.append(survey.complaint_employee_text[:60])
    if survey.complaint_conditions_text:
        parts.append(survey.complaint_conditions_text[:60])
    return "; ".join(parts) if parts else "—"


# ── Filter sentinel values ───────────────────────────────────────────────────
_FILTER_ALL         = "all"
_FILTER_IN_PROGRESS = SituationStatus.IN_PROGRESS
_FILTER_RESOLVED    = SituationStatus.RESOLVED
_FILTER_UNRESOLVED  = SituationStatus.UNRESOLVED


# ---------------------------------------------------------------------------
# Client picker dialog
# ---------------------------------------------------------------------------

class _ClientPickerDialog(QDialog):
    """Select an active client to log a new complaint against."""

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session = session
        self._all_clients: list[Client] = []
        self._shown_clients: list[Client] = []
        self._picked: Client | None = None
        self._build_ui()
        self._load()
        self.setWindowTitle("Выбор клиента для жалобы")
        self.setMinimumSize(380, 440)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Поиск:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("ФИО ребёнка или родителя…")
        self._search_edit.textChanged.connect(self._filter)
        search_row.addWidget(self._search_edit)
        root.addLayout(search_row)

        self._list = QListWidget()
        self._list.doubleClicked.connect(self._accept_selection)
        root.addWidget(self._list)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Выбрать")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        btns.accepted.connect(self._accept_selection)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _load(self) -> None:
        self._all_clients = (
            self._session.query(Client)
            .filter(Client.status == ClientStatus.ACTIVE)
            .order_by(Client.child_name)
            .all()
        )
        self._update_list(self._all_clients)

    def _filter(self, text: str) -> None:
        t = text.strip().lower()
        if t:
            filtered = [
                c for c in self._all_clients
                if t in c.child_name.lower()
                or (c.parent_name and t in c.parent_name.lower())
            ]
        else:
            filtered = list(self._all_clients)
        self._update_list(filtered)

    def _update_list(self, clients: list[Client]) -> None:
        self._shown_clients = clients
        self._list.clear()
        for c in clients:
            label = c.child_name
            if c.parent_name:
                label += f"  ({c.parent_name})"
            self._list.addItem(label)
        if clients:
            self._list.setCurrentRow(0)

    def _accept_selection(self) -> None:
        idx = self._list.currentRow()
        if idx >= 0:
            self._picked = self._shown_clients[idx]
            self.accept()

    @property
    def picked_client(self) -> Client | None:
        return self._picked


class ComplaintsWidget(QWidget):
    """Complaint-situation management tab — identical structure to EmployeesWidget."""

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session = session
        self._surveys: list[Survey] = []
        self._build_ui()
        self.load_data()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Toolbar ──────────────────────────────────────────────────
        bar = QHBoxLayout()

        bar.addWidget(QLabel("Статус:"))
        self._status_filter = QComboBox()
        self._status_filter.addItem("В процессе",  _FILTER_IN_PROGRESS)
        self._status_filter.addItem("Улажена",     _FILTER_RESOLVED)
        self._status_filter.addItem("Не улажена",  _FILTER_UNRESOLVED)
        self._status_filter.addItem("Все жалобы",  _FILTER_ALL)
        self._status_filter.currentIndexChanged.connect(self.load_data)
        bar.addWidget(self._status_filter)

        self._new_complaint_btn = QPushButton("Новая жалоба")
        self._new_complaint_btn.clicked.connect(self._new_complaint)
        bar.addWidget(self._new_complaint_btn)

        bar.addStretch()

        self._add_contact_btn = QPushButton("Добавить контакт")
        self._add_contact_btn.setEnabled(False)
        self._add_contact_btn.clicked.connect(self._add_contact)

        self._edit_btn = QPushButton("Редактировать")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._edit_survey)

        self._del_btn = QPushButton("Удалить")
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._delete_survey)

        bar.addWidget(self._add_contact_btn)
        bar.addWidget(self._edit_btn)
        bar.addWidget(self._del_btn)
        root.addLayout(bar)

        # ── Table ─────────────────────────────────────────────────────
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels([
            "Клиент", "Тип жалобы", "Детали", "Удовлетв.",
            "Статус", "Контактов", "Дата",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.itemSelectionChanged.connect(self._on_sel)
        self._table.doubleClicked.connect(self._edit_survey)
        root.addWidget(self._table)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def load_data(self) -> None:
        status_filter = self._status_filter.currentData()

        # Base query: any survey with a negative signal
        q = (
            self._session.query(Survey)
            .join(Survey.client)
            .filter(or_(
                Survey.complaint_employee == True,       # noqa: E712
                Survey.complaint_conditions == True,     # noqa: E712
                Survey.satisfaction == Satisfaction.UNSATISFIED,
                Survey.misunderstanding == Misunderstanding.YES,
            ))
            .order_by(Client.child_name, Survey.contact_date)
        )

        if status_filter != _FILTER_ALL:
            q = q.filter(Survey.situation_status == status_filter)

        self._surveys = q.all()
        self._table.setRowCount(len(self._surveys))

        for row, s in enumerate(self._surveys):
            client_name  = s.client.child_name if s.client else "—"
            comp_type    = _complaint_type(s)
            detail       = _complaint_detail(s)
            sat          = s.satisfaction.value if s.satisfaction else "—"
            sit          = s.situation_status.value if s.situation_status else "—"
            contact_cnt  = str(len(s.client.surveys)) if s.client else "—"
            dt           = s.contact_date.strftime("%d.%m.%Y") if s.contact_date else "—"

            status_bg = _STATUS_BG.get(s.situation_status)
            status_fg = _STATUS_FG.get(s.situation_status)

            self._table.setItem(row, 0, _ro_item(client_name))
            self._table.setItem(row, 1, _ro_item(comp_type))
            self._table.setItem(row, 2, _ro_item(detail))
            self._table.setItem(row, 3, _ro_item(sat))
            self._table.setItem(row, 4, _ro_item(sit, fg=status_fg, bg=status_bg))
            self._table.setItem(row, 5, _ro_item(contact_cnt))
            self._table.setItem(row, 6, _ro_item(dt))

        self._add_contact_btn.setEnabled(False)
        self._edit_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        log.debug("ComplaintsWidget: loaded %d rows (filter=%s)",
                  len(self._surveys), status_filter)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_sel(self) -> None:
        s = self._selected_survey()
        has = s is not None
        # "Добавить контакт" — только для ситуаций «В процессе»
        can_add = has and s.situation_status == SituationStatus.IN_PROGRESS
        self._add_contact_btn.setEnabled(can_add)
        self._edit_btn.setEnabled(has)
        self._del_btn.setEnabled(has)

    def _selected_survey(self) -> Survey | None:
        rows = self._table.selectionModel().selectedRows()
        return self._surveys[rows[0].row()] if rows else None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _delete_survey(self) -> None:
        s = self._selected_survey()
        if s is None:
            return
        client_name = s.client.child_name if s.client else "—"
        dt = s.contact_date.strftime("%d.%m.%Y") if s.contact_date else "без даты"
        msg = (
            f"Удалить запись жалобы от {dt}\n"
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
            log.info("Deleted complaint survey id=%s", s.id)
            self.load_data()
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to delete complaint survey")
            QMessageBox.critical(self, "Ошибка", str(exc))

    def _new_complaint(self) -> None:
        """Pick a client, then open a survey form to log a new complaint."""
        picker = _ClientPickerDialog(self._session, parent=self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        client = picker.picked_client
        if client is None:
            return
        from ui.survey_form_widget import SurveyFormDialog
        dlg = SurveyFormDialog(self._session, client.id, parent=self)
        dlg.survey_saved.connect(self.load_data)
        dlg.exec()

    def _add_contact(self) -> None:
        """Open a blank survey form for an extra contact with the same client."""
        s = self._selected_survey()
        if s is None:
            return
        from ui.survey_form_widget import SurveyFormDialog
        dlg = SurveyFormDialog(self._session, s.client_id, parent=self)
        dlg.survey_saved.connect(self.load_data)
        dlg.exec()

    def _edit_survey(self) -> None:
        """Edit the selected complaint survey."""
        s = self._selected_survey()
        if s is None:
            return
        from ui.survey_form_widget import SurveyFormDialog
        dlg = SurveyFormDialog(self._session, s.client_id, survey=s, parent=self)
        dlg.survey_saved.connect(self.load_data)
        dlg.exec()
