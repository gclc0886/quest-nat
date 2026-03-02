"""
Database backup and restore utilities.

Backups are plain copies of the SQLite file saved to data/backups/
with a timestamp in the filename.
"""
import logging
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH    = Path("data/surveys.db")
BACKUP_DIR = Path("data/backups")


def create_backup() -> Path:
    """
    Copy the current SQLite database to data/backups/ with a timestamp.

    Returns the path of the created backup file.
    Raises FileNotFoundError if the database doesn't exist.
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(f"База данных не найдена: {DB_PATH}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"backup_{ts}.db"
    shutil.copy2(DB_PATH, dest)
    size_kb = dest.stat().st_size / 1024
    log.info("Backup created: %s (%.1f KB)", dest, size_kb)
    return dest


def restore_backup(backup_path: Path) -> None:
    """
    Replace the current database with a backup file.

    Automatically saves a pre-restore snapshot of the current database
    to data/backups/pre_restore_<timestamp>.db before overwriting.

    The caller is responsible for closing the SQLAlchemy session BEFORE
    calling this function and reopening it AFTER.

    Raises FileNotFoundError if backup_path doesn't exist.
    """
    if not Path(backup_path).exists():
        raise FileNotFoundError(f"Файл резервной копии не найден: {backup_path}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Auto-snapshot current DB before overwriting
    if DB_PATH.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot = BACKUP_DIR / f"pre_restore_{ts}.db"
        shutil.copy2(DB_PATH, snapshot)
        log.info("Pre-restore snapshot saved: %s", snapshot)

    shutil.copy2(backup_path, DB_PATH)
    log.info("Database restored from: %s", backup_path)


def list_backups() -> list[Path]:
    """Return all backup_*.db files sorted newest first."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("backup_*.db"), reverse=True)
