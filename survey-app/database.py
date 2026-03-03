import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

log = logging.getLogger(__name__)

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

DATABASE_URL = "sqlite:///./data/surveys.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def _apply_migrations() -> None:
    """Idempotent ALTER TABLE migrations for columns added after initial release."""
    from sqlalchemy import inspect, text

    try:
        inspector = inspect(engine)
        # Only migrate tables that already exist
        existing_tables = inspector.get_table_names()

        if "clients" in existing_tables:
            cols = {c["name"] for c in inspector.get_columns("clients")}
            with engine.begin() as conn:
                if "end_date" not in cols:
                    conn.execute(text("ALTER TABLE clients ADD COLUMN end_date DATE"))
                    log.info("Migration: added clients.end_date")
                if "feedback_status" not in cols:
                    conn.execute(text(
                        "ALTER TABLE clients ADD COLUMN feedback_status VARCHAR(50)"
                    ))
                    log.info("Migration: added clients.feedback_status")
                if "notes" not in cols:
                    conn.execute(text("ALTER TABLE clients ADD COLUMN notes TEXT"))
                    log.info("Migration: added clients.notes")
    except Exception as exc:
        log.warning("Migration step failed (non-fatal): %s", exc)


def init_db() -> None:
    """Create all tables. Called once on app startup."""
    # Import here to avoid circular imports
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_migrations()
    log.info("Database initialized at %s", DATABASE_URL)
