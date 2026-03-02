"""Tests for Excel migration logic."""
import os
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

from migration.import_excel import (
    MigrationResult,
    _extract_parent_name,
    _parse_date,
    run_migration,
)
from models import Client, ContactType, Survey


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_datetime_object(self):
        from datetime import datetime
        dt = datetime(2025, 11, 20, 0, 0)
        assert _parse_date(dt) == date(2025, 11, 20)

    def test_string_dot_ymd(self):
        assert _parse_date("20.11.2025") == date(2025, 11, 20)

    def test_string_dot_short_year(self):
        assert _parse_date("20.11.25") == date(2025, 11, 20)

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_invalid_returns_none(self):
        assert _parse_date(18) is None
        assert _parse_date(0.0) is None
        assert _parse_date("bad-value") is None


class TestExtractParentName:
    def test_extracts_from_survey_text(self):
        text = "[20.11.25 12:19] Андрей (Злата Дорохина 4г): Добрый день!"
        assert _extract_parent_name([text]) == "Андрей"

    def test_extracts_from_second_text_when_first_empty(self):
        text2 = "[15.01.26 13:39] Ольга (Анна Таран 3г): Здравствуйте"
        assert _extract_parent_name([None, text2]) == "Ольга"

    def test_returns_none_when_no_match(self):
        text = "Опрос направлен по WhatsApp 20.11.25 в 11:26.\n\nНе прочитано."
        assert _extract_parent_name([text]) is None

    def test_returns_none_for_empty_list(self):
        assert _extract_parent_name([]) is None

    def test_extracts_two_word_name(self):
        text = "[19.01.26 11:05] Катя (Максим Гутор 2г): Добрый день"
        assert _extract_parent_name([text]) == "Катя"


# ---------------------------------------------------------------------------
# Integration tests — run_migration with in-memory DB
# ---------------------------------------------------------------------------

@pytest.fixture
def excel_path():
    """Path to the real Excel file for integration tests."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(os.path.dirname(base), "Опросы.xlsx")
    if not os.path.exists(path):
        pytest.skip("Опросы.xlsx not found — skipping integration test")
    return path


def test_migration_creates_clients_and_surveys(db_session, excel_path):
    result = run_migration(excel_path, db_session)

    assert result.errors == []
    # Total processed = created + skipped = 67 (all clients in the file)
    assert result.clients_created + result.clients_skipped == 67
    assert result.surveys_created > 80  # at least 80 of 99 expected surveys

    # Verify all created clients are in DB.
    # Excel contains duplicate child names; those are detected as "skipped" within
    # the same migration run (autoflush makes them visible before commit), so
    # clients_in_db == clients_created (unique names), not clients_created + clients_skipped.
    clients_in_db = db_session.query(Client).count()
    assert clients_in_db == result.clients_created


def test_migration_idempotent(db_session, excel_path):
    """Running migration twice must not duplicate data."""
    run_migration(excel_path, db_session)
    result2 = run_migration(excel_path, db_session)

    assert result2.clients_created == 0
    assert result2.surveys_created == 0
    assert result2.clients_skipped == 67
    assert result2.errors == []


def test_migration_extracts_parent_names(db_session, excel_path):
    run_migration(excel_path, db_session)
    clients_with_parent = (
        db_session.query(Client)
        .filter(Client.parent_name.isnot(None))
        .count()
    )
    assert clients_with_parent > 15  # at least some parent names extracted


def test_migration_progress_callback(db_session, excel_path):
    calls = []
    run_migration(excel_path, db_session, progress_callback=lambda c, t: calls.append((c, t)))

    assert len(calls) == 67
    # First call: (1, 67), last call: (67, 67)
    assert calls[0] == (1, 67)
    assert calls[-1] == (67, 67)


def test_migration_survey_contact_types(db_session, excel_path):
    run_migration(excel_path, db_session)

    s1 = db_session.query(Survey).filter(Survey.contact_type == ContactType.PLANNED_1).count()
    s2 = db_session.query(Survey).filter(Survey.contact_type == ContactType.PLANNED_2).count()
    s3 = db_session.query(Survey).filter(Survey.contact_type == ContactType.PLANNED_3).count()

    assert s1 > 50
    assert s2 > 15
    assert s3 > 8
