# Project: Survey Tracking & Analytics System (QUEST)

## Overview

Desktop application for a children's correction center. Tracks, analyzes, and manages quality control of client surveys. Single-user, runs locally. Includes automated conflict management, analytics with charts, markdown export, and an AI-powered feedback processing module via OpenRouter API.

Migration of existing data from an Excel file (67 clients, ~93 survey records, 2022–2026) is required.

## Core Features

- **Client management** — children + parents, start dates, status (active/finished), assigned specialists
- **Employee directory** — speech therapists, defectologists, psychologists, neuropsychologists, SI, administrators
- **Survey & communication log** — 3 planned surveys per client + unlimited additional contacts
- **Complaint tracking** — complaints about staff and center conditions with structured fields
- **Situation management** — status lifecycle: In Progress → Resolved / Unresolved / Completed
- **Analytics** — satisfaction rate, open conflicts, avg contacts to resolution, complaints by employee
- **Markdown export** — unsatisfied feedback export for external AI processing
- **AI module** — OpenRouter API integration with model selector, system prompt editor, chat interface

## Tech Stack

- **Language:** Python 3.x
- **UI Framework:** PyQt6
- **Database:** SQLite
- **ORM:** SQLAlchemy
- **Charts:** PyQtChart (bundled with PyQt6) or matplotlib
- **AI Integration:** OpenRouter API (via httpx)
- **Data Migration:** openpyxl (Excel import)

## Architecture Notes

Single-process desktop application. No HTTP server. SQLAlchemy connects directly to SQLite file. UI widgets communicate with the service layer directly (no network layer). OpenRouter API calls made from the AI service module using httpx.

## Project Structure

```
survey-app/
├── main.py                      # Entry point — QApplication setup
├── database.py                  # SQLAlchemy engine + session factory
├── models.py                    # ORM models (Client, Employee, Survey + M2M tables)
├── system_prompt.txt            # AI system prompt (editable file)
│
├── ui/                          # PyQt6 widgets and windows
│   ├── main_window.py           # QMainWindow — tab bar / navigation
│   ├── clients_widget.py        # Clients list + add/edit form
│   ├── client_detail_widget.py  # Client card + survey timeline
│   ├── employees_widget.py      # Employees list + form
│   ├── surveys_widget.py        # Surveys table with filters
│   ├── survey_form_widget.py    # Create/edit survey form (all complaint blocks)
│   ├── analytics_widget.py      # Analytics dashboard + charts
│   └── ai_module_widget.py      # AI chat window with model selector
│
├── services/                    # Business logic (no UI dependencies)
│   ├── survey_logic.py          # Auto-status rules, planned survey creation
│   ├── analytics.py             # KPI calculations
│   ├── export.py                # Markdown export builder
│   └── ai_service.py            # OpenRouter API calls (httpx async)
│
└── migration/                   # One-time data import
    └── import_excel.py          # Migrate Опросы.xlsx → SQLite
```

## Data Models

### Clients
- `id`, `child_name`, `parent_name`, `start_date`, `status` (active/finished)
- M2M with employees (current specialists)

### Employees
- `id`, `full_name`, `position` (logoped/defectolog/psycholog/neuropsy/si/admin), `status`

### Surveys
- `id`, `client_id`, `contact_date`, `contact_type` (planned_1/2/3/additional)
- `conducted_by`, `comment_text`, `satisfaction`, `misunderstanding`
- `complaint_employee`, `complaint_employee_text` (+ M2M to employees)
- `complaint_conditions`, `complaint_conditions_text`
- `situation_status`, `resolution_result`, `non_resolution_reason`
- M2M snapshot of specialists at time of survey

## Automatic Business Logic

- Creating a client auto-generates 3 planned survey templates
- If satisfaction = "unsatisfied" OR misunderstanding = "yes" OR any complaint:
  → `situation_status` = "In Progress"
- If `resolution_result` filled → `situation_status` = "Resolved"
- If `non_resolution_reason` filled → `situation_status` = "Unresolved"
- Contact count per client is auto-calculated

## Analytics

| Metric | Logic |
|--------|-------|
| % satisfied clients | COUNT(satisfaction=satisfied) / COUNT(not null) |
| Open conflicts | COUNT(situation_status=in_progress) |
| Avg contacts to resolution | AVG(contacts) WHERE resolved |
| Complaints by employee | JOIN survey_complaint_employees GROUP BY employee |
| Condition complaint categories | Text analysis of complaint_conditions_text |
| Repeat contacts | Clients with survey count > 3 |

## Architecture
See `.ai-factory/ARCHITECTURE.md` for detailed architecture guidelines.
Pattern: Layered Architecture (ui → services → models/db)

## Non-Functional Requirements

- Language: Russian UI
- Single user, local machine only
- No HTTP server — direct SQLite access
- Logging: Python logging module (LOG_LEVEL configurable)
- Error handling: QMessageBox for user-facing errors, logging for debug
- Export: Markdown file saved to disk
- AI: OpenRouter API key stored in local config file (not in DB)
