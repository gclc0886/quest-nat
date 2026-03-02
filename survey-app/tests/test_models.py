"""Tests for ORM models — no PyQt6, pure SQLAlchemy."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, init_db
from models import (
    Client, ClientStatus,
    Employee, EmployeePosition, EmployeeStatus,
    Survey, ContactType, Satisfaction, Misunderstanding, SituationStatus,
)


def test_create_employee(db_session):
    emp = Employee(
        full_name="Иванова Анна Сергеевна",
        position=EmployeePosition.LOGOPED,
        status=EmployeeStatus.ACTIVE,
    )
    db_session.add(emp)
    db_session.commit()
    db_session.refresh(emp)

    assert emp.id is not None
    assert emp.full_name == "Иванова Анна Сергеевна"
    assert emp.position == EmployeePosition.LOGOPED
    assert emp.status == EmployeeStatus.ACTIVE


def test_create_client(db_session):
    client = Client(
        child_name="Петров Иван",
        parent_name="Петрова Мария",
        start_date=date(2024, 9, 1),
        status=ClientStatus.ACTIVE,
    )
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)

    assert client.id is not None
    assert client.child_name == "Петров Иван"
    assert client.parent_name == "Петрова Мария"
    assert client.start_date == date(2024, 9, 1)
    assert client.status == ClientStatus.ACTIVE


def test_create_survey(db_session):
    client = Client(child_name="Сидорова Катя", status=ClientStatus.ACTIVE)
    db_session.add(client)
    db_session.flush()

    survey = Survey(
        client_id=client.id,
        contact_date=date(2025, 1, 15),
        contact_type=ContactType.PLANNED_1,
        conducted_by="Я",
        comment_text="Всё хорошо",
        satisfaction=Satisfaction.SATISFIED,
        misunderstanding=Misunderstanding.NO,
        complaint_employee=False,
        complaint_conditions=False,
    )
    db_session.add(survey)
    db_session.commit()
    db_session.refresh(survey)

    assert survey.id is not None
    assert survey.client_id == client.id
    assert survey.satisfaction == Satisfaction.SATISFIED
    assert survey.contact_type == ContactType.PLANNED_1
    assert survey.situation_status is None


def test_client_employee_relationship(db_session):
    emp = Employee(
        full_name="Козлова Елена",
        position=EmployeePosition.PSYCHOLOG,
        status=EmployeeStatus.ACTIVE,
    )
    client = Client(child_name="Новиков Артём", status=ClientStatus.ACTIVE)
    client.specialists.append(emp)

    db_session.add_all([emp, client])
    db_session.commit()
    db_session.refresh(client)

    assert len(client.specialists) == 1
    assert client.specialists[0].full_name == "Козлова Елена"


def test_survey_complaint_employee_relationship(db_session):
    emp = Employee(
        full_name="Соколов Дмитрий",
        position=EmployeePosition.DEFECTOLOG,
        status=EmployeeStatus.ACTIVE,
    )
    client = Client(child_name="Морозова Аня", status=ClientStatus.ACTIVE)
    db_session.add_all([emp, client])
    db_session.flush()

    survey = Survey(
        client_id=client.id,
        contact_type=ContactType.PLANNED_2,
        complaint_employee=True,
        complaint_employee_text="Опоздание на занятие",
        situation_status=SituationStatus.IN_PROGRESS,
    )
    survey.complaint_employees.append(emp)
    db_session.add(survey)
    db_session.commit()
    db_session.refresh(survey)

    assert len(survey.complaint_employees) == 1
    assert survey.complaint_employees[0].full_name == "Соколов Дмитрий"
    assert survey.situation_status == SituationStatus.IN_PROGRESS


def test_database_init():
    """init_db() creates all tables without errors (uses temp in-memory DB)."""
    engine = create_engine("sqlite:///:memory:")
    # Patch the global engine used by init_db
    import database
    original_engine = database.engine
    database.engine = engine
    try:
        init_db()
        # Verify tables exist
        from sqlalchemy import inspect
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        assert "clients" in table_names
        assert "employees" in table_names
        assert "surveys" in table_names
        assert "client_employees" in table_names
        assert "survey_complaint_employees" in table_names
        assert "survey_specialists_snapshot" in table_names
    finally:
        database.engine = original_engine


def test_client_surveys_cascade_delete(db_session):
    client = Client(child_name="Волков Серёжа", status=ClientStatus.ACTIVE)
    db_session.add(client)
    db_session.flush()

    survey = Survey(client_id=client.id, contact_type=ContactType.PLANNED_1)
    db_session.add(survey)
    db_session.commit()
    survey_id = survey.id

    db_session.delete(client)
    db_session.commit()

    deleted = db_session.get(Survey, survey_id)
    assert deleted is None
