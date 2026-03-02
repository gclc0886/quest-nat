"""Tests for services/survey_logic.py and services/analytics.py."""
from datetime import date

import pytest

from models import (
    Client, ClientStatus, ContactType, Misunderstanding, Satisfaction,
    SituationStatus, Survey,
)
from services.survey_logic import (
    auto_update_status,
    create_planned_surveys,
    create_survey,
    get_contact_count,
    update_survey,
)
from services.analytics import (
    get_analytics_summary,
    get_avg_contacts_to_resolve,
    get_conflict_stats,
    get_employee_complaint_counts,
    get_monthly_trend,
    get_repeat_clients_count,
    get_satisfaction_stats,
)
from services.export import build_unsatisfied_report, export_to_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(session, name="Тестов Тест") -> Client:
    c = Client(child_name=name, status=ClientStatus.ACTIVE)
    session.add(c)
    session.flush()
    return c


def _make_survey(session, client_id, **kwargs) -> Survey:
    defaults = dict(
        client_id=client_id,
        contact_type=ContactType.PLANNED_1,
        conducted_by="Я",
    )
    defaults.update(kwargs)
    s = Survey(**defaults)
    session.add(s)
    session.flush()
    return s


# ---------------------------------------------------------------------------
# auto_update_status
# ---------------------------------------------------------------------------

class TestAutoUpdateStatus:
    def test_no_signal_leaves_status_none(self):
        s = Survey(client_id=1)
        auto_update_status(s)
        assert s.situation_status is None

    def test_unsatisfied_sets_in_progress(self):
        s = Survey(client_id=1, satisfaction=Satisfaction.UNSATISFIED)
        auto_update_status(s)
        assert s.situation_status == SituationStatus.IN_PROGRESS

    def test_misunderstanding_sets_in_progress(self):
        s = Survey(client_id=1, misunderstanding=Misunderstanding.YES)
        auto_update_status(s)
        assert s.situation_status == SituationStatus.IN_PROGRESS

    def test_complaint_employee_sets_in_progress(self):
        s = Survey(client_id=1, complaint_employee=True)
        auto_update_status(s)
        assert s.situation_status == SituationStatus.IN_PROGRESS

    def test_complaint_conditions_sets_in_progress(self):
        s = Survey(client_id=1, complaint_conditions=True)
        auto_update_status(s)
        assert s.situation_status == SituationStatus.IN_PROGRESS

    def test_resolution_result_sets_resolved(self):
        s = Survey(client_id=1, satisfaction=Satisfaction.UNSATISFIED,
                   resolution_result="Вопрос урегулирован")
        auto_update_status(s)
        assert s.situation_status == SituationStatus.RESOLVED

    def test_non_resolution_reason_sets_unresolved(self):
        s = Survey(client_id=1, complaint_employee=True,
                   non_resolution_reason="Отказался от контакта")
        auto_update_status(s)
        assert s.situation_status == SituationStatus.UNRESOLVED

    def test_resolution_takes_priority_over_non_resolution(self):
        # Both filled — resolution wins
        s = Survey(client_id=1,
                   resolution_result="Решено",
                   non_resolution_reason="Причина")
        auto_update_status(s)
        assert s.situation_status == SituationStatus.RESOLVED

    def test_negative_signal_does_not_override_existing_status(self):
        # If status already set, rule 1 should NOT override
        s = Survey(client_id=1,
                   satisfaction=Satisfaction.UNSATISFIED,
                   situation_status=SituationStatus.RESOLVED)
        auto_update_status(s)
        # resolution_result is None → rule 2 doesn't fire; non_resolution is None → rule 3 doesn't fire
        # rule 1 only fires if situation_status is None — so status stays RESOLVED
        assert s.situation_status == SituationStatus.RESOLVED

    def test_whitespace_resolution_result_does_not_trigger(self):
        s = Survey(client_id=1, satisfaction=Satisfaction.UNSATISFIED,
                   resolution_result="   ")
        auto_update_status(s)
        # Whitespace-only → rule 2 doesn't fire → rule 1 fires
        assert s.situation_status == SituationStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# create_survey / update_survey / create_planned_surveys / get_contact_count
# ---------------------------------------------------------------------------

class TestSurveyCRUD:
    def test_create_survey_persists(self, db_session):
        client = _make_client(db_session)
        data = {
            "contact_type": ContactType.PLANNED_1,
            "contact_date": date(2026, 1, 15),
            "comment_text": "Всё хорошо",
        }
        survey = create_survey(db_session, client.id, data)
        assert survey.id is not None
        assert db_session.query(Survey).count() == 1

    def test_create_survey_auto_status(self, db_session):
        client = _make_client(db_session)
        survey = create_survey(db_session, client.id, {
            "satisfaction": Satisfaction.UNSATISFIED,
        })
        assert survey.situation_status == SituationStatus.IN_PROGRESS

    def test_update_survey_changes_fields(self, db_session):
        client = _make_client(db_session)
        survey = _make_survey(db_session, client.id)
        update_survey(db_session, survey, {
            "satisfaction": Satisfaction.SATISFIED,
            "comment_text": "Отлично",
        })
        assert survey.satisfaction == Satisfaction.SATISFIED
        assert survey.comment_text == "Отлично"

    def test_update_survey_triggers_auto_status(self, db_session):
        client = _make_client(db_session)
        survey = _make_survey(db_session, client.id)
        assert survey.situation_status is None
        update_survey(db_session, survey, {"complaint_employee": True})
        assert survey.situation_status == SituationStatus.IN_PROGRESS

    def test_create_planned_surveys_creates_three(self, db_session):
        client = _make_client(db_session)
        surveys = create_planned_surveys(db_session, client.id)
        assert len(surveys) == 3
        types = {s.contact_type for s in surveys}
        assert types == {ContactType.PLANNED_1, ContactType.PLANNED_2, ContactType.PLANNED_3}

    def test_get_contact_count(self, db_session):
        client = _make_client(db_session)
        assert get_contact_count(db_session, client.id) == 0
        _make_survey(db_session, client.id)
        _make_survey(db_session, client.id, contact_type=ContactType.PLANNED_2)
        assert get_contact_count(db_session, client.id) == 2


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class TestAnalytics:
    def _populate(self, session):
        """Create two clients with a mix of surveys."""
        c1 = _make_client(session, "Клиент Один")
        c2 = _make_client(session, "Клиент Два")

        # c1: 2 satisfied surveys
        _make_survey(session, c1.id,
                     contact_type=ContactType.PLANNED_1,
                     contact_date=date(2025, 11, 1),
                     satisfaction=Satisfaction.SATISFIED)
        _make_survey(session, c1.id,
                     contact_type=ContactType.PLANNED_2,
                     contact_date=date(2025, 12, 1),
                     satisfaction=Satisfaction.SATISFIED)
        # c2: 1 unsatisfied + 1 resolved
        s3 = _make_survey(session, c2.id,
                          contact_type=ContactType.PLANNED_1,
                          contact_date=date(2025, 11, 15),
                          satisfaction=Satisfaction.UNSATISFIED)
        auto_update_status(s3)
        session.flush()

        s4 = _make_survey(session, c2.id,
                          contact_type=ContactType.PLANNED_2,
                          contact_date=date(2026, 1, 10),
                          satisfaction=Satisfaction.SATISFIED,
                          resolution_result="Урегулировано")
        auto_update_status(s4)
        session.flush()

        return c1, c2

    def test_satisfaction_stats(self, db_session):
        self._populate(db_session)
        stats = get_satisfaction_stats(db_session)
        assert stats.total_with_answer == 4
        assert stats.satisfied == 3
        assert stats.unsatisfied == 1
        assert stats.satisfaction_pct == 75.0

    def test_conflict_stats(self, db_session):
        self._populate(db_session)
        stats = get_conflict_stats(db_session)
        assert stats.in_progress == 1
        assert stats.resolved == 1

    def test_avg_contacts_to_resolve_returns_value(self, db_session):
        self._populate(db_session)
        avg = get_avg_contacts_to_resolve(db_session)
        # c2 has 2 surveys and has a resolved one → avg = 2.0
        assert avg == 2.0

    def test_avg_contacts_to_resolve_none_when_no_resolved(self, db_session):
        _make_client(db_session)
        avg = get_avg_contacts_to_resolve(db_session)
        assert avg is None

    def test_repeat_clients_count(self, db_session):
        client = _make_client(db_session)
        for ct in (ContactType.PLANNED_1, ContactType.PLANNED_2,
                   ContactType.PLANNED_3, ContactType.ADDITIONAL):
            _make_survey(db_session, client.id, contact_type=ct)
        count = get_repeat_clients_count(db_session, threshold=3)
        assert count == 1

    def test_monthly_trend_aggregates(self, db_session):
        c = _make_client(db_session)
        _make_survey(db_session, c.id,
                     contact_date=date(2025, 11, 1),
                     satisfaction=Satisfaction.SATISFIED)
        _make_survey(db_session, c.id,
                     contact_date=date(2025, 11, 20),
                     satisfaction=Satisfaction.UNSATISFIED)
        _make_survey(db_session, c.id,
                     contact_date=date(2025, 12, 5),
                     satisfaction=Satisfaction.SATISFIED)

        trend = get_monthly_trend(db_session)
        assert len(trend) == 2
        nov = trend[0]
        assert nov.year == 2025 and nov.month == 11
        assert nov.total == 2
        assert nov.satisfied == 1
        assert nov.satisfaction_pct == 50.0

    def test_full_summary(self, db_session):
        self._populate(db_session)
        summary = get_analytics_summary(db_session)
        assert summary.total_clients == 2
        assert summary.total_surveys == 4
        assert summary.satisfaction.satisfied == 3


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExport:
    def test_no_problematic_surveys(self, db_session):
        client = _make_client(db_session)
        _make_survey(db_session, client.id, satisfaction=Satisfaction.SATISFIED)
        report = build_unsatisfied_report(db_session)
        assert "не найдено" in report

    def test_report_contains_client_name(self, db_session):
        client = _make_client(db_session, "Иванов Иван")
        _make_survey(db_session, client.id,
                     satisfaction=Satisfaction.UNSATISFIED)
        report = build_unsatisfied_report(db_session)
        assert "Иванов Иван" in report
        assert "### Опрос:" in report

    def test_export_to_file(self, db_session, tmp_path):
        client = _make_client(db_session, "Петров Петя")
        _make_survey(db_session, client.id, complaint_employee=True)
        out = tmp_path / "report.md"
        count = export_to_file(db_session, out)
        assert count == 1
        text = out.read_text(encoding="utf-8")
        assert "Петров Петя" in text
