"""Employees management tab widget."""
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy.orm import Session

from models import Employee, EmployeePosition, EmployeeStatus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ro_item(text: str, color: QColor | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if color:
        item.setForeground(color)
    return item


def _set_combo(cb: QComboBox, value) -> None:
    for i in range(cb.count()):
        if cb.itemData(i) == value:
            cb.setCurrentIndex(i)
            return


# ---------------------------------------------------------------------------
# Add / edit dialog
# ---------------------------------------------------------------------------

class _EmployeeDialog(QDialog):
    def __init__(self, session: Session, employee: Employee | None = None,
                 parent=None):
        super().__init__(parent)
        self._session  = session
        self._employee = employee
        self._build_ui()
        if employee:
            self._populate()
        self.setWindowTitle(
            "Редактировать сотрудника" if employee else "Новый сотрудник"
        )
        self.setMinimumWidth(380)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        f    = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Иванова Анна Петровна")
        f.addRow("ФИО:", self._name_edit)
        root.addLayout(f)

        # ── Positions checkboxes ──────────────────────────────────────
        pos_group  = QGroupBox("Должности")
        pos_layout = QVBoxLayout(pos_group)
        pos_layout.setSpacing(4)
        self._pos_checks: dict[EmployeePosition, QCheckBox] = {}
        for pos in EmployeePosition:
            cb = QCheckBox(pos.value)
            self._pos_checks[pos] = cb
            pos_layout.addWidget(cb)
        root.addWidget(pos_group)

        # ── Status (edit-mode only) ───────────────────────────────────
        if self._employee:
            st_form = QFormLayout()
            self._status_cb: QComboBox | None = QComboBox()
            for st in EmployeeStatus:
                self._status_cb.addItem(st.value, st)
            st_form.addRow("Статус:", self._status_cb)
            root.addLayout(st_form)
        else:
            self._status_cb = None

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _populate(self) -> None:
        self._name_edit.setText(self._employee.full_name)
        current = set(self._employee.positions_list)
        for pos, cb in self._pos_checks.items():
            cb.setChecked(pos.value in current)
        if self._status_cb:
            _set_combo(self._status_cb, self._employee.status)

    def _save(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Введите ФИО сотрудника.")
            return

        selected = [
            pos.value
            for pos, cb in self._pos_checks.items()
            if cb.isChecked()
        ]
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы одну должность.")
            return

        position_str = ",".join(selected)

        try:
            if self._employee is None:
                emp = Employee(
                    full_name=name,
                    position=position_str,
                    status=EmployeeStatus.ACTIVE,
                )
                self._session.add(emp)
            else:
                self._employee.full_name = name
                self._employee.position  = position_str
                if self._status_cb:
                    self._employee.status = self._status_cb.currentData()
            self._session.commit()
            log.info("Employee saved: %r positions=%s", name, position_str)
            self.accept()
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to save employee")
            QMessageBox.critical(self, "Ошибка", str(exc))


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class EmployeesWidget(QWidget):
    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session   = session
        self._employees: list[Employee] = []
        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self._add_btn    = QPushButton("Добавить")
        self._add_btn.clicked.connect(self._add)
        self._edit_btn   = QPushButton("Редактировать")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._edit)
        self._toggle_btn = QPushButton("Изменить статус")
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.clicked.connect(self._toggle_status)
        self._del_btn    = QPushButton("Удалить")
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._delete)
        bar.addWidget(self._add_btn)
        bar.addWidget(self._edit_btn)
        bar.addWidget(self._toggle_btn)
        bar.addWidget(self._del_btn)
        bar.addStretch()
        root.addLayout(bar)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["ID", "ФИО", "Должности", "Статус"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(0, 40)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_sel)
        self._table.doubleClicked.connect(self._edit)
        root.addWidget(self._table)

    # ------------------------------------------------------------------
    def load_data(self) -> None:
        self._employees = (
            self._session.query(Employee)
            .order_by(Employee.full_name)
            .all()
        )
        self._table.setRowCount(len(self._employees))
        gray = QColor("#888888")
        for row, emp in enumerate(self._employees):
            inactive = emp.status == EmployeeStatus.INACTIVE
            color    = gray if inactive else None
            self._table.setItem(row, 0, _ro_item(str(emp.id), color))
            self._table.setItem(row, 1, _ro_item(emp.full_name, color))
            self._table.setItem(row, 2, _ro_item(emp.positions_display, color))
            self._table.setItem(row, 3, _ro_item(emp.status.value, color))
        self._edit_btn.setEnabled(False)
        self._toggle_btn.setEnabled(False)
        self._del_btn.setEnabled(False)

    # ------------------------------------------------------------------
    def _on_sel(self) -> None:
        has = bool(self._table.selectionModel().selectedRows())
        self._edit_btn.setEnabled(has)
        self._toggle_btn.setEnabled(has)
        self._del_btn.setEnabled(has)

    def _selected(self) -> Employee | None:
        rows = self._table.selectionModel().selectedRows()
        return self._employees[rows[0].row()] if rows else None

    def _add(self) -> None:
        dlg = _EmployeeDialog(self._session, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.load_data()

    def _edit(self) -> None:
        emp = self._selected()
        if emp is None:
            return
        dlg = _EmployeeDialog(self._session, employee=emp, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.load_data()

    def _delete(self) -> None:
        emp = self._selected()
        if emp is None:
            return
        msg = (
            f"Удалить сотрудника «{emp.full_name}»?\n\n"
            "Сотрудник будет удалён из всех клиентских карточек и опросов.\n"
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
            self._session.delete(emp)
            self._session.commit()
            log.info("Deleted employee %r", emp.full_name)
            self.load_data()
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to delete employee")
            QMessageBox.critical(self, "Ошибка", str(exc))

    def _toggle_status(self) -> None:
        emp = self._selected()
        if emp is None:
            return
        try:
            emp.status = (
                EmployeeStatus.INACTIVE
                if emp.status == EmployeeStatus.ACTIVE
                else EmployeeStatus.ACTIVE
            )
            self._session.commit()
            log.info("Employee %r status → %s", emp.full_name, emp.status.value)
            self.load_data()
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to toggle employee status")
            QMessageBox.critical(self, "Ошибка", str(exc))
