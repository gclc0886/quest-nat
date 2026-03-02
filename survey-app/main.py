import sys
import logging
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from database import SessionLocal, init_db
from services.config_store import load_config
from ui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

_UI_DIR = Path(__file__).parent / "ui"


def main() -> None:
    log.info("Starting application")
    init_db()

    app = QApplication(sys.argv)
    app.setApplicationName("QUEST — Система учёта опросов")

    icon_path = _UI_DIR / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
        log.debug("App icon loaded: %s", icon_path)

    cfg = load_config()
    dark = cfg.get("theme", "light") == "dark"

    qss_name = "styles_dark.qss" if dark else "styles.qss"
    qss_path = _UI_DIR / qss_name
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
        log.debug("Stylesheet loaded: %s", qss_name)

    session = SessionLocal()
    log.info("Database session opened")

    window = MainWindow(session, dark=dark)
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
