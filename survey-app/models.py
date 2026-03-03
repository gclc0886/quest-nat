import enum
from calendar import monthrange
from datetime import date
from typing import List, Optional

from sqlalchemy import (
    Boolean, Date, Enum, ForeignKey, Integer, String, Table, Text, Column,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# ---------------------------------------------------------------------------
# M2M association tables
# ---------------------------------------------------------------------------

client_employees = Table(
    "client_employees",
    Base.metadata,
    Column("client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True),
    Column("employee_id", Integer, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
)

survey_complaint_employees = Table(
    "survey_complaint_employees",
    Base.metadata,
    Column("survey_id", Integer, ForeignKey("surveys.id", ondelete="CASCADE"), primary_key=True),
    Column("employee_id", Integer, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
)

survey_specialists_snapshot = Table(
    "survey_specialists_snapshot",
    Base.metadata,
    Column("survey_id", Integer, ForeignKey("surveys.id", ondelete="CASCADE"), primary_key=True),
    Column("employee_id", Integer, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EmployeePosition(str, enum.Enum):
    LOGOPED    = "Логопед"
    DEFECTOLOG = "Дефектолог"
    PSYCHOLOG  = "Психолог"
    NEUROPSY   = "Нейропсихолог"
    SI         = "СИ"
    ABA        = "ABA"
    ADMIN      = "Администратор"


class EmployeeStatus(str, enum.Enum):
    ACTIVE   = "Активен"
    INACTIVE = "Не работает"


class ClientStatus(str, enum.Enum):
    ACTIVE   = "Активен"
    FINISHED = "Завершён"


class ContactType(str, enum.Enum):
    PLANNED_1  = "Плановый 1"
    PLANNED_2  = "Плановый 2"
    PLANNED_3  = "Плановый 3"
    ADDITIONAL = "Дополнительный"


class Satisfaction(str, enum.Enum):
    SATISFIED   = "Доволен"
    UNSATISFIED = "Не доволен"


class Misunderstanding(str, enum.Enum):
    YES = "Да"
    NO  = "Нет"


class SituationStatus(str, enum.Enum):
    IN_PROGRESS = "В процессе"
    RESOLVED    = "Улажена"
    UNRESOLVED  = "Не улажена"
    CLOSED      = "Завершена"


class FeedbackStatus(str, enum.Enum):
    SENT     = "Прислали обратную связь"
    NOT_SENT = "Не прислали обратную связь"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Employee(Base):
    __tablename__ = "employees"

    id:        Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Stores one or more EmployeePosition values joined by comma,
    # e.g. "Логопед" or "Логопед,Дефектолог".
    # String instead of Enum to support multiple positions per employee.
    position: Mapped[str] = mapped_column(String(500), nullable=False)

    status: Mapped[EmployeeStatus] = mapped_column(
        Enum(EmployeeStatus, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        default=EmployeeStatus.ACTIVE,
    )

    # Relationships
    clients: Mapped[List["Client"]] = relationship(
        "Client", secondary=client_employees, back_populates="specialists"
    )
    complaint_surveys: Mapped[List["Survey"]] = relationship(
        "Survey", secondary=survey_complaint_employees, back_populates="complaint_employees"
    )
    snapshot_surveys: Mapped[List["Survey"]] = relationship(
        "Survey", secondary=survey_specialists_snapshot, back_populates="specialists_snapshot"
    )

    # ------------------------------------------------------------------
    # Position helpers
    # ------------------------------------------------------------------

    @property
    def positions_list(self) -> list[str]:
        """Returns position values as a list, e.g. ['Логопед', 'Дефектолог']."""
        if not self.position:
            return []
        return [p.strip() for p in self.position.split(",") if p.strip()]

    @property
    def positions_display(self) -> str:
        """Human-readable comma-separated string, e.g. 'Логопед, Дефектолог'."""
        return ", ".join(self.positions_list)

    def __repr__(self) -> str:
        return f"<Employee id={self.id} name={self.full_name!r} position={self.position!r}>"


class Client(Base):
    __tablename__ = "clients"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    child_name:  Mapped[str]           = mapped_column(String(200), nullable=False)
    parent_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    start_date:  Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date:    Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status:      Mapped[ClientStatus]  = mapped_column(
        Enum(ClientStatus, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        default=ClientStatus.ACTIVE,
    )
    feedback_status: Mapped[Optional[FeedbackStatus]] = mapped_column(
        Enum(FeedbackStatus, values_callable=lambda e: [x.value for x in e]),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    specialists: Mapped[List[Employee]] = relationship(
        "Employee", secondary=client_employees, back_populates="clients"
    )
    surveys: Mapped[List["Survey"]] = relationship(
        "Survey", back_populates="client", cascade="all, delete-orphan", order_by="Survey.contact_date"
    )

    # ------------------------------------------------------------------
    # Duration helpers (computed, not stored in DB)
    # ------------------------------------------------------------------

    @property
    def duration_display(self) -> str:
        """Formatted duration 'X мес Y дн'. Empty string if dates missing/invalid."""
        if not self.start_date or not self.end_date:
            return ""
        if self.end_date < self.start_date:
            return ""
        y1, m1, d1 = self.start_date.year, self.start_date.month, self.start_date.day
        y2, m2, d2 = self.end_date.year,   self.end_date.month,   self.end_date.day
        months = (y2 - y1) * 12 + (m2 - m1)
        if d2 < d1:
            months -= 1
            prev_m = m2 - 1 if m2 > 1 else 12
            prev_y = y2 if m2 > 1 else y2 - 1
            prev_last = monthrange(prev_y, prev_m)[1]
            days = (prev_last - d1) + d2 + 1
        else:
            days = d2 - d1
        parts = []
        if months:
            parts.append(f"{months} мес")
        if days:
            parts.append(f"{days} дн")
        return " ".join(parts) or "0 дн"

    @property
    def duration_days(self) -> int:
        """Total days between start and end date. -1 if unavailable (for sorting)."""
        if not self.start_date or not self.end_date or self.end_date < self.start_date:
            return -1
        return (self.end_date - self.start_date).days

    def __repr__(self) -> str:
        return f"<Client id={self.id} child={self.child_name!r} status={self.status.value}>"


class Survey(Base):
    __tablename__ = "surveys"

    id:         Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id:  Mapped[int] = mapped_column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    contact_date: Mapped[Optional[date]]        = mapped_column(Date, nullable=True)
    contact_type: Mapped[Optional[ContactType]] = mapped_column(
        Enum(ContactType, values_callable=lambda e: [x.value for x in e]),
        nullable=True,
    )
    conducted_by: Mapped[str]           = mapped_column(String(200), nullable=False, default="Я")
    comment_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Satisfaction block
    satisfaction: Mapped[Optional[Satisfaction]] = mapped_column(
        Enum(Satisfaction, values_callable=lambda e: [x.value for x in e]),
        nullable=True,
    )
    misunderstanding: Mapped[Optional[Misunderstanding]] = mapped_column(
        Enum(Misunderstanding, values_callable=lambda e: [x.value for x in e]),
        nullable=True,
        default=Misunderstanding.NO,
    )

    # Complaint: employee
    complaint_employee:      Mapped[bool]          = mapped_column(Boolean, nullable=False, default=False)
    complaint_employee_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Complaint: conditions
    complaint_conditions:      Mapped[bool]          = mapped_column(Boolean, nullable=False, default=False)
    complaint_conditions_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Situation management
    situation_status:    Mapped[Optional[SituationStatus]] = mapped_column(
        Enum(SituationStatus, values_callable=lambda e: [x.value for x in e]),
        nullable=True,
    )
    resolution_result:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    non_resolution_reason:Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    client: Mapped[Client] = relationship("Client", back_populates="surveys")
    complaint_employees: Mapped[List[Employee]] = relationship(
        "Employee", secondary=survey_complaint_employees, back_populates="complaint_surveys"
    )
    specialists_snapshot: Mapped[List[Employee]] = relationship(
        "Employee", secondary=survey_specialists_snapshot, back_populates="snapshot_surveys"
    )

    def __repr__(self) -> str:
        return (
            f"<Survey id={self.id} client_id={self.client_id} "
            f"type={self.contact_type} date={self.contact_date}>"
        )
