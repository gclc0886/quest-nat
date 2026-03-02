# AGENTS.md

> Project map for AI agents. Keep this file up-to-date as the project evolves.

## Project Overview

Desktop application (PyQt6) for a children's correction center for tracking, analyzing, and managing quality control of client surveys. Single-user, runs locally. Includes automated conflict management, analytics charts, markdown export, and an AI-powered feedback processing module (OpenRouter API).

## Tech Stack

- **Language:** Python 3.x
- **UI Framework:** PyQt6
- **Database:** SQLite
- **ORM:** SQLAlchemy
- **Charts:** PyQtChart or matplotlib
- **AI Integration:** OpenRouter API (httpx)
- **Data Migration:** openpyxl

## Project Structure

```
QUEST/                              # Project root
├── survey-app/                     # Application code (to be created)
│   ├── main.py                     # Entry point — QApplication, DB init, session, main window
│   ├── database.py                 # SQLAlchemy engine + SessionLocal + Base
│   ├── models.py                   # All ORM models (Client, Employee, Survey + M2M tables)
│   ├── system_prompt.txt           # AI system prompt (editable without code change)
│   │
│   ├── ui/                         # [Presentation layer — PyQt6 widgets only]
│   │   ├── main_window.py          # QMainWindow with QTabWidget navigation
│   │   ├── clients_widget.py       # Clients table + add/edit dialog
│   │   ├── client_detail_widget.py # Client card + survey history timeline
│   │   ├── employees_widget.py     # Employees table + form
│   │   ├── surveys_widget.py       # Surveys table with filter controls
│   │   ├── survey_form_widget.py   # QDialog — full survey form (complaints, resolution)
│   │   ├── analytics_widget.py     # KPI labels + charts
│   │   └── ai_module_widget.py     # Chat window, model selector, system prompt editor
│   │
│   ├── services/                   # [Business logic — no PyQt6 imports]
│   │   ├── survey_logic.py         # auto_update_status(), create_planned_surveys()
│   │   ├── analytics.py            # KPI queries and aggregations
│   │   ├── export.py               # Build markdown + save to file
│   │   └── ai_service.py           # OpenRouter API (AIChatWorker QThread)
│   │
│   └── migration/                  # [Utility — run once]
│       └── import_excel.py         # openpyxl → SQLAlchemy bulk insert
│
├── .ai-factory/                    # AI agent context
│   ├── DESCRIPTION.md              # Full project specification
│   └── ARCHITECTURE.md             # Architecture decisions and guidelines
├── .claude/                        # Claude Code config
│   ├── skills/                     # Agent skills
│   └── launch.json                 # Dev server configuration
├── .mcp.json                       # MCP server configuration
├── Application-Task.txt            # Original requirements (Russian)
├── DEVELOPMENT_PLAN.md             # 7-phase development plan
├── System-Prompt.txt               # AI system prompt template
└── Опросы.xlsx                     # Source data (67 clients, ~93 surveys)
```

## Key Entry Points

| File | Purpose |
|------|---------|
| `survey-app/main.py` | Start here — launches the application |
| `survey-app/models.py` | Source of truth for DB schema |
| `survey-app/services/survey_logic.py` | Core business rules (auto-status) |
| `survey-app/migration/import_excel.py` | Run once to import Excel data |

## Key Business Rules

1. Each client gets **3 planned survey templates** on registration
2. Survey triggers `situation_status = "In Progress"` when: satisfaction=unsatisfied OR misunderstanding=yes OR any complaint
3. `resolution_result` filled → status = "Resolved"
4. `non_resolution_reason` filled → status = "Unresolved"
5. Contact count per client is derived (not stored)
6. Services NEVER import from `ui/` — no PyQt6 in service layer
7. All AI/network calls run in `QThread` to avoid blocking the UI

## Documentation

| Document | Path | Description |
|----------|------|-------------|
| Project specification | `.ai-factory/DESCRIPTION.md` | Tech stack, features, data models |
| Architecture | `.ai-factory/ARCHITECTURE.md` | Layered desktop pattern, code examples |
| Development plan | `DEVELOPMENT_PLAN.md` | 7-phase implementation plan |
| Requirements (RU) | `Application-Task.txt` | Original Russian requirements |

## AI Context Files

| File | Purpose |
|------|---------|
| `AGENTS.md` | This file — project structure map |
| `.ai-factory/DESCRIPTION.md` | Full project specification and tech stack |
| `.ai-factory/ARCHITECTURE.md` | Architecture decisions and guidelines |
| `System-Prompt.txt` | AI system prompt for analytics module |
