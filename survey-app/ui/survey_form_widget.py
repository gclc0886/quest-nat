"""Survey creation / editing dialog."""
import logging
from datetime import date

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLineEdit, QMessageBox,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)
from sqlalchemy.orm import Session

from models import ContactType, Misunderstanding, Satisfaction, SituationStatus, Survey
from services.survey_logic import create_survey, update_survey

log = logging.getLogger(__name__)

_CT_OPTIONS = [
    (None, "— не указан —"),
    (ContactType.PLANNED_1,  ContactType.PLANNED_1.value),
    (ContactType.PLANNED_2,  ContactType.PLANNED_2.value),
    (ContactType.PLANNED_3,  ContactType.PLANNED_3.value),
    (ContactType.ADDITIONAL, ContactType.ADDITIONAL.value),
]

_SAT_OPTIONS = [
    (None, "— не указана —"),
    (Satisfaction.SATISFIED,   Satisfaction.SATISFIED.value),
    (Satisfaction.UNSATISFIED, Satisfaction.UNSATISFIED.value),
]

_SIT_OPTIONS = [
    (None, "— не указан —"),
    (SituationStatus.IN_PROGRESS, SituationStatus.IN_PROGRESS.value),
    (SituationStatus.RESOLVED,    SituationStatus.RESOLVED.value),
    (SituationStatus.UNRESOLVED,  SituationStatus.UNRESOLVED.value),
    (SituationStatus.CLOSED,      SituationStatus.CLOSED.value),
]


def _combo(options: list) -> QComboBox:
    cb = QComboBox()
    for val, label in options:
        cb.addItem(label, val)
    return cb


def _set_combo(cb: QComboBox, value) -> None:
    for i in range(cb.count()):
        if cb.itemData(i) == value:
            cb.setCurrentIndex(i)
            return


class SurveyFormDialog(QDialog):
    """Create-or-edit dialog for a Survey record.

    Pass *survey=None* to create a new survey, or an existing Survey
    object to edit it.  Emits *survey_saved* after successful commit.
    """

    survey_saved = pyqtSignal()

    def __init__(self, session: Session, client_id: int,
                 survey: Survey | None = None, parent=None):
        super().__init__(parent)
        self._session = session
        self._client_id = client_id
        self._survey = survey
        self._build_ui()
        if survey:
            self._populate(survey)
        self.setWindowTitle("Редактировать опрос" if survey else "Новый опрос")
        self.setMinimumWidth(540)
        self.resize(580, 680)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_l = QVBoxLayout(inner)
        inner_l.setSpacing(8)
        inner_l.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        # ── Basic info ──────────────────────────────────────────────
        g1 = QGroupBox("Основная информация")
        f1 = QFormLayout(g1)

        self._type_cb = _combo(_CT_OPTIONS)
        f1.addRow("Тип контакта:", self._type_cb)

        self._date_check = QCheckBox("Указать дату")
        self._date_edit = QDateEdit(QDate.currentDate())
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("dd.MM.yyyy")
        self._date_edit.setEnabled(False)
        self._date_check.toggled.connect(self._date_edit.setEnabled)
        date_row = QWidget()
        date_row_l = QHBoxLayout(date_row)
        date_row_l.setContentsMargins(0, 0, 0, 0)
        date_row_l.addWidget(self._date_check)
        date_row_l.addWidget(self._date_edit)
        date_row_l.addStretch()
        f1.addRow("Дата контакта:", date_row)

        self._conducted_edit = QLineEdit("Я")
        f1.addRow("Провёл:", self._conducted_edit)

        self._comment_edit = QTextEdit()
        self._comment_edit.setPlaceholderText("Текст опроса…")
        self._comment_edit.setFixedHeight(90)
        f1.addRow("Комментарий:", self._comment_edit)

        inner_l.addWidget(g1)

        # ── Satisfaction ─────────────────────────────────────────────
        g2 = QGroupBox("Удовлетворённость")
        f2 = QFormLayout(g2)

        self._sat_cb = _combo(_SAT_OPTIONS)
        f2.addRow("Оценка:", self._sat_cb)

        self._misunder_check = QCheckBox("Было недопонимание")
        f2.addRow("", self._misunder_check)

        inner_l.addWidget(g2)

        # ── Complaints ───────────────────────────────────────────────
        g3 = QGroupBox("Жалобы")
        f3 = QFormLayout(g3)

        self._comp_emp_check = QCheckBox("Жалоба на сотрудника")
        f3.addRow(self._comp_emp_check)
        self._comp_emp_text = QTextEdit()
        self._comp_emp_text.setPlaceholderText("Суть жалобы…")
        self._comp_emp_text.setFixedHeight(55)
        self._comp_emp_text.setVisible(False)
        f3.addRow(self._comp_emp_text)
        self._comp_emp_check.toggled.connect(self._comp_emp_text.setVisible)

        self._comp_cond_check = QCheckBox("Жалоба на условия")
        f3.addRow(self._comp_cond_check)
        self._comp_cond_text = QTextEdit()
        self._comp_cond_text.setPlaceholderText("Описание проблемы…")
        self._comp_cond_text.setFixedHeight(55)
        self._comp_cond_text.setVisible(False)
        f3.addRow(self._comp_cond_text)
        self._comp_cond_check.toggled.connect(self._comp_cond_text.setVisible)

        inner_l.addWidget(g3)

        # ── Situation management ──────────────────────────────────────
        g4 = QGroupBox("Управление ситуацией")
        f4 = QFormLayout(g4)

        self._sit_cb = _combo(_SIT_OPTIONS)
        f4.addRow("Статус:", self._sit_cb)

        self._resolution_edit = QTextEdit()
        self._resolution_edit.setPlaceholderText("Результат урегулирования…")
        self._resolution_edit.setFixedHeight(55)
        f4.addRow("Результат:", self._resolution_edit)

        self._non_res_edit = QTextEdit()
        self._non_res_edit.setPlaceholderText("Причина неурегулирования…")
        self._non_res_edit.setFixedHeight(55)
        f4.addRow("Причина неурег.:", self._non_res_edit)

        inner_l.addWidget(g4)
        inner_l.addStretch()

        # ── Buttons ───────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ------------------------------------------------------------------
    # Pre-fill when editing
    # ------------------------------------------------------------------

    def _populate(self, s: Survey) -> None:
        _set_combo(self._type_cb, s.contact_type)
        if s.contact_date:
            self._date_check.setChecked(True)
            self._date_edit.setDate(
                QDate(s.contact_date.year, s.contact_date.month, s.contact_date.day)
            )
        self._conducted_edit.setText(s.conducted_by or "Я")
        self._comment_edit.setPlainText(s.comment_text or "")

        _set_combo(self._sat_cb, s.satisfaction)
        self._misunder_check.setChecked(s.misunderstanding == Misunderstanding.YES)

        self._comp_emp_check.setChecked(bool(s.complaint_employee))
        self._comp_emp_text.setPlainText(s.complaint_employee_text or "")
        self._comp_cond_check.setChecked(bool(s.complaint_conditions))
        self._comp_cond_text.setPlainText(s.complaint_conditions_text or "")

        _set_combo(self._sit_cb, s.situation_status)
        self._resolution_edit.setPlainText(s.resolution_result or "")
        self._non_res_edit.setPlainText(s.non_resolution_reason or "")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _collect(self) -> dict:
        contact_date = None
        if self._date_check.isChecked():
            qd = self._date_edit.date()
            contact_date = date(qd.year(), qd.month(), qd.day())
        return {
            "contact_type":             self._type_cb.currentData(),
            "contact_date":             contact_date,
            "conducted_by":             self._conducted_edit.text().strip() or "Я",
            "comment_text":             self._comment_edit.toPlainText().strip() or None,
            "satisfaction":             self._sat_cb.currentData(),
            "misunderstanding":         (
                Misunderstanding.YES if self._misunder_check.isChecked()
                else Misunderstanding.NO
            ),
            "complaint_employee":       self._comp_emp_check.isChecked(),
            "complaint_employee_text":  self._comp_emp_text.toPlainText().strip() or None,
            "complaint_conditions":     self._comp_cond_check.isChecked(),
            "complaint_conditions_text": self._comp_cond_text.toPlainText().strip() or None,
            "situation_status":         self._sit_cb.currentData(),
            "resolution_result":        self._resolution_edit.toPlainText().strip() or None,
            "non_resolution_reason":    self._non_res_edit.toPlainText().strip() or None,
        }

    def _save(self) -> None:
        data = self._collect()
        try:
            if self._survey is None:
                create_survey(self._session, self._client_id, data)
            else:
                update_survey(self._session, self._survey, data)
            self._session.commit()
            log.info("Survey saved for client_id=%s", self._client_id)
            self.survey_saved.emit()
            self.accept()
        except Exception as exc:
            self._session.rollback()
            log.exception("Failed to save survey")
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{exc}")
