"""
Export service — generates a Markdown report of unsatisfied / problematic surveys.

Format per survey:
  ## Клиент: <child_name>
  ### Опрос: <contact_type> | <contact_date>
  **Удовлетворённость**: ...
  **Недопонимание**: ...
  **Жалоба на сотрудника**: ...
  **Жалоба на условия**: ...
  **Статус ситуации**: ...
  **Комментарий**: ...
  ---
"""
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from models import Misunderstanding, Satisfaction, SituationStatus, Survey

log = logging.getLogger(__name__)

# Surveys are considered "problematic" if any negative flag is set
_NEGATIVE_STATUSES = {
    SituationStatus.IN_PROGRESS,
    SituationStatus.UNRESOLVED,
}


def _is_problematic(survey: Survey) -> bool:
    return (
        survey.satisfaction == Satisfaction.UNSATISFIED
        or survey.misunderstanding == Misunderstanding.YES
        or survey.complaint_employee
        or survey.complaint_conditions
        or survey.situation_status in _NEGATIVE_STATUSES
    )


def _format_date(d: Optional[date]) -> str:
    return d.strftime("%d.%m.%Y") if d else "—"


def _survey_block(survey: Survey) -> str:
    """Render one survey as a Markdown block."""
    contact_type = (
        survey.contact_type.value if survey.contact_type else "—"
    )
    lines = [
        f"### Опрос: {contact_type} | {_format_date(survey.contact_date)}",
    ]

    if survey.satisfaction:
        lines.append(f"**Удовлетворённость**: {survey.satisfaction.value}")
    if survey.misunderstanding:
        lines.append(f"**Недопонимание**: {survey.misunderstanding.value}")

    if survey.complaint_employee:
        complaint_text = survey.complaint_employee_text or ""
        lines.append(f"**Жалоба на сотрудника**: {complaint_text}")

    if survey.complaint_conditions:
        conditions_text = survey.complaint_conditions_text or ""
        lines.append(f"**Жалоба на условия**: {conditions_text}")

    if survey.situation_status:
        lines.append(f"**Статус ситуации**: {survey.situation_status.value}")
    if survey.resolution_result:
        lines.append(f"**Результат урегулирования**: {survey.resolution_result}")
    if survey.non_resolution_reason:
        lines.append(f"**Причина неурегулирования**: {survey.non_resolution_reason}")
    if survey.comment_text:
        lines.append(f"**Комментарий**:\n{survey.comment_text}")

    lines.append("---")
    return "\n".join(lines)


def build_unsatisfied_report(session: Session) -> str:
    """
    Build a Markdown string with all problematic surveys, grouped by client.
    Returns an empty-report message if nothing problematic is found.
    """
    # Load all surveys with their clients, sorted by client name then date
    surveys = (
        session.query(Survey)
        .join(Survey.client)
        .order_by(Survey.client_id, Survey.contact_date)
        .all()
    )

    problematic = [s for s in surveys if _is_problematic(s)]
    log.info("build_unsatisfied_report: %d problematic surveys out of %d total",
             len(problematic), len(surveys))

    if not problematic:
        return "# Неудовлетворённые обратные связи\n\nПроблемных опросов не найдено."

    # Group by client
    by_client: dict[int, list[Survey]] = {}
    for s in problematic:
        by_client.setdefault(s.client_id, []).append(s)

    sections = ["# Неудовлетворённые обратные связи\n"]
    for client_id, client_surveys in by_client.items():
        client = client_surveys[0].client
        sections.append(f"## Клиент: {client.child_name}")
        if client.parent_name:
            sections.append(f"*Родитель: {client.parent_name}*")
        sections.append("")
        for survey in client_surveys:
            sections.append(_survey_block(survey))
        sections.append("")

    return "\n".join(sections)


def export_to_file(session: Session, filepath: str | Path) -> int:
    """
    Write the unsatisfied-surveys report to *filepath* (UTF-8 Markdown).

    Returns the number of problematic surveys written.
    """
    filepath = Path(filepath)
    content = build_unsatisfied_report(session)

    filepath.write_text(content, encoding="utf-8")
    log.info("Exported report to %s (%d bytes)", filepath, len(content.encode()))

    # Count lines with "### Опрос:" as a proxy for survey count
    count = content.count("### Опрос:")
    return count
