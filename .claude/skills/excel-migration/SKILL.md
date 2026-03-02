---
name: excel-migration
description: Migrate data from Excel (.xlsx) files to a SQLite/SQLAlchemy database using openpyxl. Use when implementing data import scripts, Excel-to-DB migration, or parsing unstructured Excel data.
---

# Excel Migration Skill

Patterns and best practices for migrating data from Excel files to SQLAlchemy/SQLite databases using openpyxl. Covers reading, parsing, regex extraction from text fields, bulk insert, and migration reporting.

## When to Use This Skill

- Importing historical data from Excel into a new application database
- Parsing unstructured text fields in Excel to extract structured data
- Running one-time or idempotent Excel-to-DB migrations
- Generating migration reports (imported / failed / skipped counts)

## Core Patterns

### 1. Reading Excel with openpyxl

```python
import openpyxl
from datetime import datetime

def read_excel(filepath: str):
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active  # or wb["SheetName"]

    # Skip header row, iterate data rows
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:  # skip empty rows
            continue
        yield row
```

### 2. Date Parsing (multiple formats)

```python
def parse_date(value) -> date | None:
    """Handle datetime objects, DD.MM.YY, DD.MM.YYYY strings."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.date() if isinstance(value, datetime) else value

    s = str(value).strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None  # unparseable — log and skip
```

### 3. Regex Extraction from Free-form Text

For texts like: `[20.11.25 12:19] Андрей (Злата Дорохина 4г): Добрый день!`

```python
import re

PARENT_PATTERN = re.compile(
    r'\[\d{2}\.\d{2}\.\d{2,4}[^\]]*\]\s+([А-ЯЁа-яёA-Za-z]+)\s+\('
)

def extract_parent_name(text: str) -> str | None:
    """Extract parent name from survey text."""
    if not text:
        return None
    match = PARENT_PATTERN.search(text)
    return match.group(1) if match else None

# Example: extract channel (WhatsApp, MAX, etc.)
CHANNEL_PATTERN = re.compile(r'(WhatsApp|MAX|Telegram|ВКонтакте)', re.IGNORECASE)

def extract_channel(text: str) -> str | None:
    match = CHANNEL_PATTERN.search(text or "")
    return match.group(1) if match else None
```

### 4. Migration Script Structure

```python
from sqlalchemy.orm import Session
from models import Client, Survey
import logging

logger = logging.getLogger(__name__)

class MigrationResult:
    def __init__(self):
        self.clients_created = 0
        self.surveys_created = 0
        self.skipped = 0
        self.errors = []

def run_migration(filepath: str, db: Session) -> MigrationResult:
    result = MigrationResult()

    for row in read_excel(filepath):
        try:
            client = migrate_client(row, db, result)
            if client:
                migrate_surveys(row, client, db, result)
        except Exception as e:
            result.errors.append(f"Row {row[0]}: {e}")
            logger.error(f"Failed to migrate row {row[0]}: {e}")
            db.rollback()
            continue

    db.commit()
    return result

def migrate_client(row, db: Session, result: MigrationResult) -> Client | None:
    child_name = str(row[1]).strip() if row[1] else None
    if not child_name:
        result.skipped += 1
        return None

    # Idempotency: check if already exists
    existing = db.query(Client).filter(Client.child_name == child_name).first()
    if existing:
        result.skipped += 1
        return existing

    # Extract parent name from survey texts
    parent_name = None
    for text_col in [4, 7, 10]:  # text columns for surveys 1, 2, 3
        if row[text_col]:
            parent_name = extract_parent_name(str(row[text_col]))
            if parent_name:
                break

    client = Client(child_name=child_name, parent_name=parent_name, status="active")
    db.add(client)
    db.flush()  # get ID without commit
    result.clients_created += 1
    return client

def migrate_surveys(row, client: Client, db: Session, result: MigrationResult):
    """Migrate up to 3 planned surveys per client row."""
    survey_cols = [
        (3, 4, "planned_1"),  # (date_col, text_col, type)
        (6, 7, "planned_2"),
        (9, 10, "planned_3"),
    ]

    for date_col, text_col, contact_type in survey_cols:
        contact_date = parse_date(row[date_col]) if date_col < len(row) else None
        comment_text = str(row[text_col]).strip() if text_col < len(row) and row[text_col] else None

        if not contact_date and not comment_text:
            continue  # no data for this survey

        survey = Survey(
            client_id=client.id,
            contact_date=contact_date,
            contact_type=contact_type,
            comment_text=comment_text,
            conducted_by="Я",  # default
        )
        db.add(survey)
        result.surveys_created += 1
```

### 5. Migration Report Output

```python
def print_report(result: MigrationResult):
    print(f"\n=== Migration Report ===")
    print(f"Clients created:  {result.clients_created}")
    print(f"Surveys created:  {result.surveys_created}")
    print(f"Skipped (dupes):  {result.skipped}")
    print(f"Errors:           {len(result.errors)}")
    if result.errors:
        print("\nErrors:")
        for err in result.errors:
            print(f"  - {err}")
```

### 6. Entry Point

```python
# migration/import_excel.py
if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        result = run_migration("../Опросы.xlsx", db)
        print_report(result)
    finally:
        db.close()
```

## Key Rules

1. **Always use `data_only=True`** when loading workbook — gets cached values, not formulas
2. **Flush before commit** when you need IDs for related records (client → surveys)
3. **Check for None** before processing — Excel cells can be empty
4. **Idempotency** — check existing records before inserting to allow re-runs
5. **Per-row error handling** — catch and log errors per row, never abort full migration
6. **Use `db.rollback()` per failed row**, then continue — prevents partial data for one client
7. **Log everything** — migration output should show exactly what happened

## Dependencies

```
openpyxl>=3.1.0
sqlalchemy>=2.0.0
```
