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


def init_db() -> None:
    """Create all tables. Called once on app startup."""
    # Import here to avoid circular imports
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    log.info("Database initialized at %s", DATABASE_URL)
