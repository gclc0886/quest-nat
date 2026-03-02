"""
Business logic for surveys — status automation, CRUD helpers.

Rules for auto_update_status:
  1. If any negative signal (satisfaction=unsatisfied, misunderstanding=yes,
     complaint_employee=True, complaint_conditions=True)
     AND situation_status is still None → set situation_status = IN_PROGRESS
  2. If resolution_result is filled → set situation_status = RESOLVED
  3. If non_resolution_reason is filled → set situation_status = UNRESOLVED
  Priority: rule 2/3 override rule 1.
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from models import Client, ClientStatus, ContactType, FeedbackStatus, Misunderstanding, \
    Satisfaction, SituationStatus, Survey

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status automation
# ---------------------------------------------------------------------------

def auto_update_status(survey: Survey) -> None:
    """
    Apply business rules to set situation_status on *survey* in-place.
    Does NOT flush/commit — caller is responsible.
    """
    # Rule 2 (highest priority): resolution filled → RESOLVED
    if survey.resolution_result and survey.resolution_result.strip():
        survey.situation_status = SituationStatus.RESOLVED
        log.debug("Survey %s → RESOLVED (resolution_result filled)", survey.id)
        return

    # Rule 3: non-resolution reason filled → UNRESOLVED
    if survey.non_resolution_reason and survey.non_resolution_reason.strip():
        survey.situation_status = SituationStatus.UNRESOLVED
        log.debug("Survey %s → UNRESOLVED (non_resolution_reason filled)", survey.id)
        return

    # Rule 1: negative signal detected
    has_negative = (
        survey.satisfaction == Satisfaction.UNSATISFIED
        or survey.misunderstanding == Misunderstanding.YES
        or survey.complaint_employee
        or survey.complaint_conditions
    )
    if has_negative and survey.situation_status is None:
        survey.situation_status = SituationStatus.IN_PROGRESS
        log.debug("Survey %s → IN_PROGRESS (negative signal detected)", survey.id)


# ---------------------------------------------------------------------------
# Feedback status helpers
# ---------------------------------------------------------------------------

def _auto_update_feedback_status(session: Session, survey: Survey) -> None:
    """
    If a satisfaction answer is present, mark the parent client as having
    sent feedback (FeedbackStatus.SENT), unless already set.
    Does NOT flush/commit — caller is responsible.
    """
    if survey.satisfaction is None:
        return
    client = session.get(Client, survey.client_id)
    if client is None:
        return
    if client.feedback_status != FeedbackStatus.SENT:
        client.feedback_status = FeedbackStatus.SENT
        log.debug(
            "Client id=%s feedback_status → SENT (survey id=%s has satisfaction)",
            client.id, survey.id,
        )


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def create_survey(session: Session, client_id: int, data: dict) -> Survey:
    """
    Create a new Survey from *data* dict, apply auto_update_status, flush.

    Expected keys (all optional unless noted):
        contact_date, contact_type, conducted_by, comment_text,
        satisfaction, misunderstanding,
        complaint_employee, complaint_employee_text,
        complaint_conditions, complaint_conditions_text,
        situation_status, resolution_result, non_resolution_reason
    """
    survey = Survey(
        client_id=client_id,
        contact_date=data.get("contact_date"),
        contact_type=data.get("contact_type"),
        conducted_by=data.get("conducted_by", "Я"),
        comment_text=data.get("comment_text"),
        satisfaction=data.get("satisfaction"),
        misunderstanding=data.get("misunderstanding"),
        complaint_employee=bool(data.get("complaint_employee", False)),
        complaint_employee_text=data.get("complaint_employee_text"),
        complaint_conditions=bool(data.get("complaint_conditions", False)),
        complaint_conditions_text=data.get("complaint_conditions_text"),
        situation_status=data.get("situation_status"),
        resolution_result=data.get("resolution_result"),
        non_resolution_reason=data.get("non_resolution_reason"),
    )
    auto_update_status(survey)
    session.add(survey)
    session.flush()  # flush first so survey.id is available for logging
    _auto_update_feedback_status(session, survey)
    log.info("Created survey id=%s for client_id=%s type=%s",
             survey.id, client_id, survey.contact_type)
    return survey


def update_survey(session: Session, survey: Survey, data: dict) -> Survey:
    """
    Update *survey* fields from *data* dict, apply auto_update_status, flush.
    Only keys present in *data* are applied.
    """
    updatable = [
        "contact_date", "contact_type", "conducted_by", "comment_text",
        "satisfaction", "misunderstanding",
        "complaint_employee", "complaint_employee_text",
        "complaint_conditions", "complaint_conditions_text",
        "situation_status", "resolution_result", "non_resolution_reason",
    ]
    for field in updatable:
        if field in data:
            setattr(survey, field, data[field])

    auto_update_status(survey)
    _auto_update_feedback_status(session, survey)
    session.flush()
    log.info("Updated survey id=%s", survey.id)
    return survey


def create_planned_surveys(session: Session, client_id: int) -> list[Survey]:
    """
    Create three planned survey templates for a newly-added client.
    Returns the list of created (flushed) Survey objects.
    """
    surveys = []
    for contact_type in (
        ContactType.PLANNED_1,
        ContactType.PLANNED_2,
        ContactType.PLANNED_3,
    ):
        s = Survey(
            client_id=client_id,
            contact_type=contact_type,
            conducted_by="Я",
        )
        session.add(s)
        surveys.append(s)

    session.flush()
    log.info("Created 3 planned survey templates for client_id=%s", client_id)
    return surveys


def get_contact_count(session: Session, client_id: int) -> int:
    """Return the number of surveys associated with *client_id*."""
    count = session.query(Survey).filter(Survey.client_id == client_id).count()
    log.debug("client_id=%s contact_count=%s", client_id, count)
    return count
