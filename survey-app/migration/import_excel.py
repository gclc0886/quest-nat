"""
Excel migration: Опросы.xlsx → SQLite

Structure of the source file (Лист1):
  Col A (0)  — row number
  Col B (1)  — child name (ФИО ребёнка)
  Col C (2)  — survey 1 order number (not used)
  Col D (3)  — survey 1 date (datetime or None)
  Col E (4)  — survey 1 text
  Col F (5)  — survey 2 order number (not used)
  Col G (6)  — survey 2 date
  Col H (7)  — survey 2 text
  Col I (8)  — survey 3 order number (not used)
  Col J (9)  — survey 3 date
  Col K (10) — survey 3 text
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import openpyxl
from sqlalchemy.orm import Session

from models import Client, ClientStatus, ContactType, Survey

log = logging.getLogger(__name__)

# Regex: extract parent name from text like "[20.11.25 12:19] Андрей (Злата 4г):"
_PARENT_RE = re.compile(
    r'\[\d{2}\.\d{2}\.\d{2,4}[^\]]*\]\s+([А-ЯЁа-яё][а-яёА-ЯЁ]+(?:\s+[А-ЯЁа-яё]\.?)?)\s*\(',
    re.UNICODE,
)


@dataclass
class MigrationResult:
    clients_created: int = 0
    clients_skipped: int = 0
    surveys_created: int = 0
    errors: list = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return self.clients_created + self.clients_skipped + len(self.errors)

    def as_report(self) -> str:
        lines = [
            "=== Отчёт миграции ===",
            f"Клиентов создано:   {self.clients_created}",
            f"Клиентов пропущено: {self.clients_skipped}  (уже существуют)",
            f"Опросов создано:    {self.surveys_created}",
            f"Ошибок:             {len(self.errors)}",
        ]
        if self.errors:
            lines.append("\nОшибки:")
            for err in self.errors:
                lines.append(f"  • {err}")
        return "\n".join(lines)


def _parse_date(value) -> Optional[date]:
    """Convert Excel datetime / string to Python date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    log.warning("Cannot parse date: %r", value)
    return None


def _extract_parent_name(texts: list) -> Optional[str]:
    """Try to extract parent first name from survey texts."""
    for text in texts:
        if not text:
            continue
        m = _PARENT_RE.search(str(text))
        if m:
            return m.group(1).strip()
    return None


def run_migration(filepath: str, session: Session,
                  progress_callback=None) -> MigrationResult:
    """
    Read Excel file and import clients + surveys into the database.

    Args:
        filepath: absolute path to .xlsx file
        session: SQLAlchemy session (caller commits on success)
        progress_callback: optional callable(current, total) for UI progress bar

    Returns:
        MigrationResult with counts and errors
    """
    result = MigrationResult()
    log.info("Starting migration from: %s", filepath)

    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active

    # Collect data rows (skip header, skip empty client names)
    data_rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = row[1]
        if name and str(name).strip():
            data_rows.append(row)

    total = len(data_rows)
    log.info("Found %d client rows to process", total)

    for idx, row in enumerate(data_rows):
        if progress_callback:
            progress_callback(idx + 1, total)

        child_name = str(row[1]).strip()
        row_num = row[0]

        try:
            # --- Idempotency: skip if client already exists ---
            existing = (
                session.query(Client)
                .filter(Client.child_name == child_name)
                .first()
            )
            if existing:
                log.debug("Skipping existing client: %r", child_name)
                result.clients_skipped += 1
                continue

            # --- Extract parent name from survey texts ---
            texts = [row[4], row[7], row[10]]
            parent_name = _extract_parent_name(texts)

            # --- Create client ---
            client = Client(
                child_name=child_name,
                parent_name=parent_name,
                status=ClientStatus.ACTIVE,
            )
            session.add(client)
            session.flush()  # get client.id before surveys
            result.clients_created += 1
            log.debug("Created client #%s: %r (parent: %r)", row_num, child_name, parent_name)

            # --- Create surveys (up to 3) ---
            survey_slots = [
                (row[3], row[4], ContactType.PLANNED_1),
                (row[6], row[7], ContactType.PLANNED_2),
                (row[9], row[10], ContactType.PLANNED_3),
            ]

            for date_val, text_val, contact_type in survey_slots:
                contact_date = _parse_date(date_val)
                comment_text = str(text_val).strip() if text_val else None

                if contact_date is None and not comment_text:
                    continue  # no data for this survey slot

                survey = Survey(
                    client_id=client.id,
                    contact_date=contact_date,
                    contact_type=contact_type,
                    comment_text=comment_text,
                    conducted_by="Я",
                )
                session.add(survey)
                result.surveys_created += 1

        except Exception as exc:
            session.rollback()
            msg = f"Строка {row_num} ({child_name!r}): {exc}"
            log.error("Migration error — %s", msg)
            result.errors.append(msg)
            # Re-open transaction after rollback
            continue

    session.commit()
    log.info("Migration complete: %s", result.as_report())
    return result
