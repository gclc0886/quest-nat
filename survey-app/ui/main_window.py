import logging

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QLabel, QVBoxLayout,
)
from PyQt6.QtCore import Qt
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def _placeholder_tab(title: str) -> QWidget:
    """Create a placeholder widget for tabs not yet implemented."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    label = QLabel(f"{title}\n(в разработке)")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("color: #888; font-size: 16px;")
    layout.addWidget(label)
    return widget


class MainWindow(QMainWindow):
    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self.session = session
        self._build_ui()
        log.info("Main window initialized")

    def _build_ui(self) -> None:
        self.setWindowTitle("Система учёта опросов — Детский коррекционный центр")
        self.setMinimumSize(900, 600)
        self.resize(1200, 800)

        tabs = QTabWidget()
        tabs.addTab(_placeholder_tab("Клиенты"), "Клиенты")
        tabs.addTab(_placeholder_tab("Сотрудники"), "Сотрудники")
        tabs.addTab(_placeholder_tab("Опросы"), "Опросы")
        tabs.addTab(_placeholder_tab("Аналитика"), "Аналитика")
        tabs.addTab(_placeholder_tab("AI-модуль"), "AI-модуль")

        self.setCentralWidget(tabs)
        self._tabs = tabs
