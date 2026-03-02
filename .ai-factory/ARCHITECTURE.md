# Architecture: Layered Architecture (Desktop)

## Overview

The project follows a Layered Architecture adapted for a **PyQt6 desktop application**. Three layers: **UI** (PyQt6 widgets), **Services** (business logic), **Data** (SQLAlchemy + SQLite). The UI layer calls services directly — no HTTP, no network layer.

This pattern was chosen because the app is single-user, runs locally, and has moderate domain complexity. Desktop layered architecture gives fast development, simple deployment (one Python process), and clean separation between UI code and business logic.

## Decision Rationale

- **Project type:** Single-user desktop app, local SQLite
- **Tech stack:** Python + PyQt6 + SQLAlchemy
- **Key factor:** No server needed — direct DB access, simple deployment (`python main.py`)
- **Trade-off accepted:** Not accessible from other machines — acceptable, single user requirement

## Folder Structure

```
survey-app/
├── main.py                      # QApplication init, main window launch, DB init
├── database.py                  # SQLAlchemy engine, SessionLocal, get_session()
├── models.py                    # All ORM models + M2M tables
├── system_prompt.txt            # AI system prompt — editable without code change
│
├── ui/                          # [LAYER 1: Presentation — PyQt6 only]
│   ├── main_window.py           # QMainWindow with QTabWidget navigation
│   ├── clients_widget.py        # QTableWidget + add/edit dialog
│   ├── client_detail_widget.py  # Client info + survey timeline
│   ├── employees_widget.py      # Employees table + form
│   ├── surveys_widget.py        # Surveys table with filter controls
│   ├── survey_form_widget.py    # QDialog — full survey form with all blocks
│   ├── analytics_widget.py      # Charts (PyQtChart / matplotlib) + KPI labels
│   └── ai_module_widget.py      # Chat window, model selector, system prompt editor
│
├── services/                    # [LAYER 2: Business Logic — no PyQt6 imports]
│   ├── survey_logic.py          # auto_update_status(), create_planned_surveys()
│   ├── analytics.py             # KPI queries, aggregations
│   ├── export.py                # Build + save markdown file
│   └── ai_service.py            # OpenRouter API calls (httpx)
│
└── migration/                   # [UTILITY — run once]
    └── import_excel.py          # openpyxl → SQLAlchemy bulk insert
```

## Dependency Rules

```
ui/ → services/ → models.py + database.py
                         ↓
                      SQLite file

ui/        calls      services/
services/  uses       models.py (ORM objects)
services/  uses       database.py (session)
models.py  knows nothing about services or ui
```

- ✅ `ui/` imports from `services/` and `models.py` (read-only for display)
- ✅ `services/` imports from `models.py` and `database.py`
- ✅ `ui/` may pass SQLAlchemy objects to widgets for display
- ❌ `services/` NEVER imports from `ui/` — no PyQt6 in service layer
- ❌ `models.py` NEVER imports from `services/` or `ui/`
- ❌ Business logic NEVER lives in widget code — no `if satisfaction == "unsatisfied"` in widgets
- ❌ `services/` NEVER opens DB sessions itself — receives `session` as argument

## Layer Communication

- **UI → Service:** Widget calls `survey_logic.create_survey(session, data)`, receives ORM object back
- **Session management:** `main_window.py` holds one `Session` for the app lifetime (single user = no concurrency issues); passed to services as argument
- **Signals/Slots:** Widgets emit Qt signals to refresh sibling widgets after data changes (e.g., after saving a survey → emit `survey_saved` signal → clients list refreshes)
- **Errors:** Services raise `ValueError` with Russian messages → widgets catch and show `QMessageBox.warning()`
- **Async AI calls:** `ai_service.py` uses `httpx` — run in `QThread` to avoid blocking the UI

## Key Principles

1. **No PyQt6 in services** — service layer must be testable without a Qt app running
2. **One session, passed down** — open `SessionLocal()` in main window, pass to every service call
3. **`auto_update_status()` always runs** — called inside `create_survey()` and `update_survey()` before commit
4. **Widgets are dumb** — collect form data → call service → refresh display. No logic inside.
5. **QThread for AI** — OpenRouter calls go in a `QThread` worker to keep UI responsive

## Code Examples

### Widget calls service (thin widget)

```python
# ui/survey_form_widget.py
from PyQt6.QtWidgets import QDialog, QMessageBox
from services import survey_logic

class SurveyFormDialog(QDialog):
    def __init__(self, session, client_id, survey=None, parent=None):
        super().__init__(parent)
        self.session = session
        self.client_id = client_id
        self.survey = survey  # None = create, object = edit
        self._build_ui()
        if survey:
            self._populate_fields(survey)

    def _on_save_clicked(self):
        data = self._collect_form_data()  # returns plain dict
        try:
            if self.survey:
                survey_logic.update_survey(self.session, self.survey, data)
            else:
                survey_logic.create_survey(self.session, self.client_id, data)
            self.accept()  # close dialog, signal success
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
```

### Service (no PyQt6, pure logic)

```python
# services/survey_logic.py
from sqlalchemy.orm import Session
import models

def auto_update_status(survey: models.Survey) -> None:
    if (
        survey.satisfaction == "unsatisfied"
        or survey.misunderstanding == "yes"
        or survey.complaint_employee
        or survey.complaint_conditions
    ):
        if survey.situation_status is None:
            survey.situation_status = "in_progress"
    if survey.resolution_result:
        survey.situation_status = "resolved"
    elif survey.non_resolution_reason:
        survey.situation_status = "unresolved"

def create_survey(session: Session, client_id: int, data: dict) -> models.Survey:
    survey = models.Survey(client_id=client_id, **data)
    auto_update_status(survey)
    session.add(survey)
    session.commit()
    session.refresh(survey)
    return survey

def create_planned_surveys(session: Session, client_id: int) -> None:
    for contact_type in ["planned_1", "planned_2", "planned_3"]:
        session.add(models.Survey(client_id=client_id, contact_type=contact_type))
    session.commit()
```

### QThread for OpenRouter API call

```python
# services/ai_service.py
from PyQt6.QtCore import QThread, pyqtSignal
import httpx

class AIChatWorker(QThread):
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, messages, model, api_key, system_prompt):
        super().__init__()
        self.messages = messages
        self.model = model
        self.api_key = api_key
        self.system_prompt = system_prompt

    def run(self):
        try:
            full_messages = [{"role": "system", "content": self.system_prompt}] + self.messages
            with httpx.Client(timeout=60.0) as client:
                r = client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "messages": full_messages},
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                self.response_ready.emit(content)
        except Exception as e:
            self.error_occurred.emit(str(e))
```

### Session management in main window

```python
# main.py
from PyQt6.QtWidgets import QApplication
from database import SessionLocal, Base, engine
from ui.main_window import MainWindow
import sys

def main():
    Base.metadata.create_all(bind=engine)  # create tables if not exist
    app = QApplication(sys.argv)
    session = SessionLocal()
    window = MainWindow(session)
    window.show()
    try:
        sys.exit(app.exec())
    finally:
        session.close()

if __name__ == "__main__":
    main()
```

## Anti-Patterns

- ❌ **PyQt6 imports in services** — breaks testability, violates layer separation
- ❌ **SQL queries in widget code** — `session.query(...)` belongs in services, not widgets
- ❌ **Opening new sessions per operation** — use the single session passed from main window
- ❌ **Blocking UI with API calls** — always use `QThread` for httpx/network calls
- ❌ **Business logic in `__init__`** — widget constructors only set up UI, not business state
- ❌ **Direct model mutation in widgets** — widgets call services, services mutate models
