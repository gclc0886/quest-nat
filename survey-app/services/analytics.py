"""
Analytics service — all metric calculations without PyQt6.

All public functions accept a SQLAlchemy Session and return plain Python
dicts / lists / numbers so UI widgets can render them however they like.
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    Client, ClientStatus, ContactType, Employee,
    Misunderstanding, Satisfaction, SituationStatus,
    Survey, survey_complaint_employees,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class SatisfactionStats:
    total_with_answer: int    # surveys where satisfaction is not None
    satisfied: int
    unsatisfied: int
    satisfaction_pct: float   # 0–100


@dataclass
class ConflictStats:
    in_progress: int
    resolved: int
    unresolved: int
    closed: int


@dataclass
class EmployeeComplaintRow:
    employee_id: int
    full_name: str
    position: str
    complaint_count: int


@dataclass
class ClientSurveyRow:
    client_id: int
    child_name: str
    survey_count: int


@dataclass
class MonthlyPoint:
    year: int
    month: int
    total: int
    satisfied: int
    satisfaction_pct: float


@dataclass
class AnalyticsSummary:
    total_clients: int
    active_clients: int
    total_surveys: int
    satisfaction: SatisfactionStats
    conflicts: ConflictStats
    misunderstanding_count: int
    avg_contacts_to_resolve: Optional[float]   # None if no resolved cases
    repeat_clients: int                         # clients with > 3 surveys
    employee_complaints: list[EmployeeComplaintRow] = field(default_factory=list)
    monthly_trend: list[MonthlyPoint] = field(default_factory=list)
    # Fallback metrics — always populated regardless of satisfaction/status data
    monthly_count: list[MonthlyPoint] = field(default_factory=list)
    contact_type_dist: dict[str, int] = field(default_factory=dict)
    top_clients: list[ClientSurveyRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual metric functions
# ---------------------------------------------------------------------------

def get_satisfaction_stats(session: Session,
                           from_date: Optional[date] = None,
                           to_date: Optional[date] = None) -> SatisfactionStats:
    """Satisfaction breakdown for surveys in the optional date range."""
    q = session.query(Survey).filter(Survey.satisfaction.isnot(None))
    if from_date:
        q = q.filter(Survey.contact_date >= from_date)
    if to_date:
        q = q.filter(Survey.contact_date <= to_date)

    total = q.count()
    satisfied = q.filter(Survey.satisfaction == Satisfaction.SATISFIED).count()
    unsatisfied = q.filter(Survey.satisfaction == Satisfaction.UNSATISFIED).count()
    pct = round(satisfied / total * 100, 1) if total > 0 else 0.0

    log.debug("SatisfactionStats: total=%s sat=%s unsat=%s pct=%.1f",
              total, satisfied, unsatisfied, pct)
    return SatisfactionStats(
        total_with_answer=total,
        satisfied=satisfied,
        unsatisfied=unsatisfied,
        satisfaction_pct=pct,
    )


def get_conflict_stats(session: Session,
                       from_date: Optional[date] = None,
                       to_date: Optional[date] = None) -> ConflictStats:
    """Count surveys by situation_status."""
    def _count(status):
        q = session.query(Survey).filter(Survey.situation_status == status)
        if from_date:
            q = q.filter(Survey.contact_date >= from_date)
        if to_date:
            q = q.filter(Survey.contact_date <= to_date)
        return q.count()

    stats = ConflictStats(
        in_progress=_count(SituationStatus.IN_PROGRESS),
        resolved=_count(SituationStatus.RESOLVED),
        unresolved=_count(SituationStatus.UNRESOLVED),
        closed=_count(SituationStatus.CLOSED),
    )
    log.debug("ConflictStats: %s", stats)
    return stats


def get_avg_contacts_to_resolve(session: Session) -> Optional[float]:
    """
    Average number of surveys per client for clients who have at least
    one survey with situation_status = RESOLVED.
    Returns None if no such clients exist.
    """
    # Find client_ids that have a resolved survey
    resolved_client_ids_q = (
        session.query(Survey.client_id)
        .filter(Survey.situation_status == SituationStatus.RESOLVED)
        .distinct()
    )
    # Count total surveys per such client
    counts = (
        session.query(func.count(Survey.id))
        .filter(Survey.client_id.in_(resolved_client_ids_q))
        .group_by(Survey.client_id)
        .all()
    )
    if not counts:
        return None
    avg = sum(c[0] for c in counts) / len(counts)
    result = round(avg, 2)
    log.debug("avg_contacts_to_resolve=%.2f (n=%d clients)", result, len(counts))
    return result


def get_employee_complaint_counts(session: Session) -> list[EmployeeComplaintRow]:
    """Number of complaint surveys per employee, descending."""
    rows = (
        session.query(
            Employee.id,
            Employee.full_name,
            Employee.position,
            func.count(survey_complaint_employees.c.survey_id).label("cnt"),
        )
        .join(survey_complaint_employees,
              Employee.id == survey_complaint_employees.c.employee_id)
        .group_by(Employee.id)
        .order_by(func.count(survey_complaint_employees.c.survey_id).desc())
        .all()
    )
    result = [
        EmployeeComplaintRow(
            employee_id=r.id,
            full_name=r.full_name,
            position=r.position or "",
            complaint_count=r.cnt,
        )
        for r in rows
    ]
    log.debug("employee_complaint_counts: %d employees with complaints", len(result))
    return result


def get_repeat_clients_count(session: Session, threshold: int = 3) -> int:
    """Number of clients with more than *threshold* surveys."""
    subq = (
        session.query(Survey.client_id, func.count(Survey.id).label("cnt"))
        .group_by(Survey.client_id)
        .subquery()
    )
    count = session.query(subq).filter(subq.c.cnt > threshold).count()
    log.debug("repeat_clients (>%d surveys): %d", threshold, count)
    return count


def get_monthly_trend(session: Session,
                      from_date: Optional[date] = None,
                      to_date: Optional[date] = None) -> list[MonthlyPoint]:
    """
    Satisfaction trend grouped by year+month.
    Only surveys with contact_date and satisfaction filled are included.
    Returns list sorted by (year, month) ascending.
    """
    q = (
        session.query(Survey)
        .filter(Survey.contact_date.isnot(None))
        .filter(Survey.satisfaction.isnot(None))
    )
    if from_date:
        q = q.filter(Survey.contact_date >= from_date)
    if to_date:
        q = q.filter(Survey.contact_date <= to_date)

    surveys = q.all()

    # Aggregate in Python (portable across SQLite / other DBs)
    buckets: dict[tuple[int, int], dict] = {}
    for s in surveys:
        key = (s.contact_date.year, s.contact_date.month)
        if key not in buckets:
            buckets[key] = {"total": 0, "satisfied": 0}
        buckets[key]["total"] += 1
        if s.satisfaction == Satisfaction.SATISFIED:
            buckets[key]["satisfied"] += 1

    result = []
    for (year, month), data in sorted(buckets.items()):
        t = data["total"]
        sat = data["satisfied"]
        result.append(MonthlyPoint(
            year=year,
            month=month,
            total=t,
            satisfied=sat,
            satisfaction_pct=round(sat / t * 100, 1) if t > 0 else 0.0,
        ))

    log.debug("monthly_trend: %d data points", len(result))
    return result


def get_misunderstanding_count(session: Session,
                                from_date: Optional[date] = None,
                                to_date: Optional[date] = None) -> int:
    """Surveys where misunderstanding == YES."""
    q = session.query(Survey).filter(Survey.misunderstanding == Misunderstanding.YES)
    if from_date:
        q = q.filter(Survey.contact_date >= from_date)
    if to_date:
        q = q.filter(Survey.contact_date <= to_date)
    return q.count()


def get_monthly_survey_count(session: Session,
                             from_date: Optional[date] = None,
                             to_date: Optional[date] = None) -> list[MonthlyPoint]:
    """
    Total survey count grouped by year+month.
    Includes all surveys with a contact_date (no satisfaction filter).
    Returns list sorted by (year, month) ascending.
    """
    q = session.query(Survey).filter(Survey.contact_date.isnot(None))
    if from_date:
        q = q.filter(Survey.contact_date >= from_date)
    if to_date:
        q = q.filter(Survey.contact_date <= to_date)

    buckets: dict[tuple[int, int], int] = {}
    for s in q.all():
        key = (s.contact_date.year, s.contact_date.month)
        buckets[key] = buckets.get(key, 0) + 1

    result = [
        MonthlyPoint(year=y, month=m, total=cnt, satisfied=0, satisfaction_pct=0.0)
        for (y, m), cnt in sorted(buckets.items())
    ]
    log.debug("monthly_survey_count: %d data points", len(result))
    return result


def get_contact_type_distribution(session: Session,
                                  from_date: Optional[date] = None,
                                  to_date: Optional[date] = None) -> dict[str, int]:
    """Count surveys per ContactType label (uses all surveys, no satisfaction filter)."""
    q = session.query(Survey)
    if from_date:
        q = q.filter(Survey.contact_date >= from_date)
    if to_date:
        q = q.filter(Survey.contact_date <= to_date)

    counts: dict[str, int] = {}
    for survey in q.all():
        label = survey.contact_type.value if survey.contact_type is not None else "Не указан"
        counts[label] = counts.get(label, 0) + 1

    log.debug("contact_type_distribution: %s", counts)
    return counts


def get_top_clients_by_surveys(session: Session,
                               limit: int = 8) -> list[ClientSurveyRow]:
    """Top clients ranked by total survey count, descending."""
    rows = (
        session.query(Client.id, Client.child_name,
                      func.count(Survey.id).label("cnt"))
        .join(Survey, Survey.client_id == Client.id)
        .group_by(Client.id)
        .order_by(func.count(Survey.id).desc())
        .limit(limit)
        .all()
    )
    result = [
        ClientSurveyRow(client_id=r.id, child_name=r.child_name, survey_count=r.cnt)
        for r in rows
    ]
    log.debug("top_clients_by_surveys: %d clients", len(result))
    return result


# ---------------------------------------------------------------------------
# Full summary (used for dashboard)
# ---------------------------------------------------------------------------

def get_analytics_summary(session: Session,
                           from_date: Optional[date] = None,
                           to_date: Optional[date] = None) -> AnalyticsSummary:
    """Compute all KPIs in one call."""
    total_clients = session.query(Client).count()
    active_clients = session.query(Client).filter(
        Client.status == ClientStatus.ACTIVE
    ).count()
    total_surveys = session.query(Survey).count()

    summary = AnalyticsSummary(
        total_clients=total_clients,
        active_clients=active_clients,
        total_surveys=total_surveys,
        satisfaction=get_satisfaction_stats(session, from_date, to_date),
        conflicts=get_conflict_stats(session, from_date, to_date),
        misunderstanding_count=get_misunderstanding_count(session, from_date, to_date),
        avg_contacts_to_resolve=get_avg_contacts_to_resolve(session),
        repeat_clients=get_repeat_clients_count(session),
        employee_complaints=get_employee_complaint_counts(session),
        monthly_trend=get_monthly_trend(session, from_date, to_date),
        monthly_count=get_monthly_survey_count(session, from_date, to_date),
        contact_type_dist=get_contact_type_distribution(session, from_date, to_date),
        top_clients=get_top_clients_by_surveys(session),
    )
    log.info("AnalyticsSummary: clients=%d surveys=%d sat_pct=%.1f conflicts_in_progress=%d",
             total_clients, total_surveys,
             summary.satisfaction.satisfaction_pct,
             summary.conflicts.in_progress)
    return summary
