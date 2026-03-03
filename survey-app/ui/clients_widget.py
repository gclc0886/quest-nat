"""Clients list tab widget."""
import logging
from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from sqlalchemy.orm import Session

from models import Client, ClientStatus
from services.survey_logic import create_planned_surveys
from ui.table_utils import setup_resizable_columns

log = logging.getLogger(__name__)

_FINISHED_COLOR = QColor("#888888")


def _ro_item(text: str, color: QColor | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if color:
        item.setForeground(color)
    return item


class _DurationItem(QTableWidgetItem):
    """Table item for 'Продолжительность' that sorts numerically by total days."""

    def __init__(self, text: str, sort_days: int, color: QColor | None = None):
        super().__init__(text)
        self._sort_days = sort_days
        self.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        if color:
            self.setForeground(color)

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        if isinstance(other, _DurationItem):
            return self._sort_days < other._sort_days
        return super().__lt__(other)


# ---------------------------------------------------------------------------
# Add-client dialog
# ---------------------------------------------------------------------------

class _AddClientDialog(QDialog):
    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session = session
        self._created_client: Client | None = None
        self._build_ui()
        self.setWindowTitle("Новый клиент")
        self.setMinimumWidth(440)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        f = QFormLayout()

        self._child_name_edit = QLineEdit()
        self._child_name_edit.setPlaceholderText("Иванов Иван (обязательно)")
        f.addRow("ФИО ребёнка:", self._child_name_edit)

        self._parent_name_edit = QLineEdit()
        self._parent_name_edit.setPlaceholderText("необязательно")
        f.addRow("ФИО родителя:", self._parent_name_edit)

        # ── Дата начала ───────────────────────────────────────────────
        self._start_date_check = QCheckBox("Указать дату начала")
        self._start_date_edit = QDateEdit(QDate.currentDate())
        self._start_date_edit.setCalendarPopup(True)
        self._start_date_edit.setDisplayFormat("dd.MM.yyyy")
        self._start_date_edit.setEnabled(False)
        self._start_date_check.toggled.connect(self._start_date_edit.setEnabled)
        start_row = QWidget()
        start_row_l = QHBoxLayout(start_row)
        start_row_l.setContentsMargins(0, 0, 0, 0)
        start_row_l.addWidget(self._start_date_check)
        start_row_l.addWidget(self._start_date_edit)
        start_row_l.addStretch()
        f.addRow("Дата начала:", start_row)

        # ── Дата окончания ────────────────────────────────────────────
        self._end_date_check = QCheckBox("Указать дату окончания")
        self._end_date_edit = QDateEdit(QDate.currentDate())
        self._end_date_edit.setCalendarPopup(True)
        self._end_date_edit.setDisplayFormat("dd.MM.yyyy")
        self._end_date_edit.setEnabled(False)
        self._end_date_check.toggled.connect(self._end_date_edit.setEnabled)
        end_row = QWidget()
        end_row_l = QHBoxLayout(end_row)
        end_row_l.setContentsMargins(0, 0, 0, 0)
        end_row_l.addWidget(self._end_date_check)
        end_row_l.addWidget(self._end_date_edit)
        end_row_l.addStretch()
        f.addRow("Дата окончания:", end_row)

        self._planned_surveys_check = QCheckBox("Создать 3 плановых опроса")
        self._planned_surveys_check.setChecked(True)
        f.addRow("", self._planned_surveys_check)

        root.addLayout(f)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText("Создать")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        btns.accepted.connect(self._create)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _create(self) -> None:
        child_name = self._child_name_edit.text().strip()
        if not child_name:
            QMessageBox.warning(self, "Ошибка", "Введите ФИО ребёнка.")
            return
        try:
            start_date = None
            if self._start_date_check.isChecked():
                qd = self._start_date_edit.date()
                start_date = date(qd.year(), qd.month(), qd.day())

            end_date = None
            if self._end_date_check.isChecked():
                qd = self._end_date_edit.date()
                end_date = date(qd.year(), qd.month(), qd.day())

            # Validate: end_date must not be before start_date
            if start_date and end_date and end_date < start_date:
                QMessageBox.warning(
                    self, "Ошибка",
                    "Дата окончания не может быть раньше даты начала."
                )
                return

            client = Client(
                child_name=child_name,
                parent_name=self._parent_name_edit.text().strip() or None,
                start_date=start_date,
                end_date=end_date,
                status=ClientStatus.ACTIVE,
            )
            self._session.add(client)
            self._session.flush()

            if self._planned_surveys_check.isChecked():
                create_planned_surveys(self._session, client.id)

            self._session.commit()
            self._created_client = client
            log.info("Created client id=%s: %r", client.id, child_name)
            self.accept()
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to create client")
            QMessageBox.critical(self, "Ошибка", str(exc))

    @property
    def created_client(self) -> Client | None:
        return self._created_client


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class ClientsWidget(QWidget):
    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session = session
        self._clients: list[Client] = []
        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Filter + search bar
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Статус:"))
        self._status_filter = QComboBox()
        self._status_filter.addItem("Все", None)
        for st in ClientStatus:
            self._status_filter.addItem(st.value, st)
        self._status_filter.currentIndexChanged.connect(self.load_data)
        bar.addWidget(self._status_filter)

        bar.addWidget(QLabel("Поиск:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("ФИО ребёнка или родителя…")
        self._search_edit.textChanged.connect(self.load_data)
        bar.addWidget(self._search_edit, stretch=1)
        root.addLayout(bar)

        # Table — 8 columns
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["ФИО ребёнка", "Родитель", "Дата начала", "Дата окончания",
             "Продолжительность", "Статус", "Опросов", "Примечания"]
        )
        setup_resizable_columns(
            self._table, "clients",
            [210, 170, 100, 110, 130, 90, 70, 200],
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.itemSelectionChanged.connect(self._on_sel)
        self._table.doubleClicked.connect(self._open_detail)
        root.addWidget(self._table)

        # Buttons
        btn_bar = QHBoxLayout()
        self._add_btn = QPushButton("Добавить клиента")
        self._add_btn.clicked.connect(self._add_client)
        self._open_btn = QPushButton("Открыть карточку")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_detail)
        self._del_btn = QPushButton("Удалить клиента")
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._delete_client)
        btn_bar.addWidget(self._add_btn)
        btn_bar.addWidget(self._open_btn)
        btn_bar.addWidget(self._del_btn)
        btn_bar.addStretch()
        root.addLayout(btn_bar)

    # ------------------------------------------------------------------
    def load_data(self) -> None:
        # Disable sorting while filling to avoid index scrambling
        self._table.setSortingEnabled(False)

        status_filter = self._status_filter.currentData()
        search = self._search_edit.text().strip().lower()

        q = self._session.query(Client).order_by(Client.child_name)
        if status_filter:
            q = q.filter(Client.status == status_filter)
        clients = q.all()

        if search:
            clients = [
                c for c in clients
                if search in c.child_name.lower()
                or (c.parent_name and search in c.parent_name.lower())
            ]

        self._clients = clients
        self._table.setRowCount(len(clients))
        for row, c in enumerate(clients):
            color = _FINISHED_COLOR if c.status == ClientStatus.FINISHED else None
            start_dt  = c.start_date.strftime("%d.%m.%Y") if c.start_date else "—"
            end_dt    = c.end_date.strftime("%d.%m.%Y")   if c.end_date   else "—"
            duration  = c.duration_display or "—"
            survey_count = str(len(c.surveys))

            self._table.setItem(row, 0, _ro_item(c.child_name, color))
            self._table.setItem(row, 1, _ro_item(c.parent_name or "—", color))
            self._table.setItem(row, 2, _ro_item(start_dt, color))
            self._table.setItem(row, 3, _ro_item(end_dt, color))
            self._table.setItem(row, 4, _DurationItem(duration, c.duration_days, color))
            self._table.setItem(row, 5, _ro_item(c.status.value, color))
            self._table.setItem(row, 6, _ro_item(survey_count, color))
            self._table.setItem(row, 7, _ro_item(c.notes or "", color))

        self._open_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        self._table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    def _on_sel(self) -> None:
        has = bool(self._table.selectionModel().selectedRows())
        self._open_btn.setEnabled(has)
        self._del_btn.setEnabled(has)

    def _selected_client(self) -> Client | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        # After sorting the visible row index ≠ list index; use column 0 text
        # to match, or better: store client.id in UserRole
        item = self._table.item(rows[0].row(), 0)
        if item is None:
            return None
        name = item.text()
        for c in self._clients:
            if c.child_name == name:
                return c
        return None

    def _add_client(self) -> None:
        dlg = _AddClientDialog(self._session, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.load_data()

    def _delete_client(self) -> None:
        client = self._selected_client()
        if client is None:
            return
        survey_count = len(client.surveys)
        msg = (
            f"Удалить клиента «{client.child_name}»?\n\n"
            f"Вместе с ним будут удалены все его опросы ({survey_count} шт.).\n"
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
            self._session.delete(client)
            self._session.commit()
            log.info("Deleted client id=%s %r", client.id, client.child_name)
            self.load_data()
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to delete client")
            QMessageBox.critical(self, "Ошибка", str(exc))

    def _open_detail(self) -> None:
        client = self._selected_client()
        if client is None:
            return
        from ui.client_detail_widget import ClientDetailDialog
        dlg = ClientDetailDialog(self._session, client, parent=self)
        dlg.client_updated.connect(self.load_data)
        dlg.exec()
        self.load_data()  # refresh survey counts after close
