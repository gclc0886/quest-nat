import sys
import logging

from PyQt6.QtWidgets import QApplication

from database import SessionLocal, init_db
from ui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def main() -> None:
    log.info("Starting application")
    init_db()

    app = QApplication(sys.argv)
    app.setApplicationName("QUEST — Система учёта опросов")

    session = SessionLocal()
    log.info("Database session opened")

    window = MainWindow(session)
    window.show()

    try:
        exit_code = app.exec()
        log.info("Application exiting with code %d", exit_code)
        sys.exit(exit_code)
    finally:
        session.close()
        log.info("Database session closed")


if __name__ == "__main__":
    main()
