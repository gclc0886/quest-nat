import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QMainWindow, QMenu,
    QMessageBox, QTabWidget,
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt
from sqlalchemy.orm import Session

from ui.ai_module_widget import AiModuleWidget
from ui.analytics_widget import AnalyticsWidget
from ui.clients_widget import ClientsWidget
from ui.complaints_widget import ComplaintsWidget
from ui.employees_widget import EmployeesWidget
from ui.surveys_widget import SurveysWidget

log = logging.getLogger(__name__)

_STYLES_DIR = Path(__file__).parent


class MainWindow(QMainWindow):
    def __init__(self, session: Session, dark: bool = False, parent=None):
        super().__init__(parent)
        self.session = session
        self._dark = dark
        self._build_ui()
        self._build_menu()
        if dark:
            self._analytics_widget.set_dark_theme(True)
        log.info("Main window initialized (dark=%s)", dark)

    def _build_ui(self) -> None:
        self.setWindowTitle("Система учёта опросов — Детский коррекционный центр")
        self.setMinimumSize(900, 600)
        self.resize(1200, 800)

        self._clients_widget    = ClientsWidget(self.session)
        self._employees_widget  = EmployeesWidget(self.session)
        self._surveys_widget    = SurveysWidget(self.session)
        self._complaints_widget = ComplaintsWidget(self.session)
        self._analytics_widget  = AnalyticsWidget(self.session)
        self._ai_widget         = AiModuleWidget(self.session)

        tabs = QTabWidget()
        tabs.addTab(self._clients_widget,    "Клиенты")
        tabs.addTab(self._employees_widget,  "Сотрудники")
        tabs.addTab(self._surveys_widget,    "Опросы")
        tabs.addTab(self._complaints_widget, "Жалобы")
        tabs.addTab(self._analytics_widget,  "Аналитика")
        tabs.addTab(self._ai_widget,         "AI-модуль")

        self.setCentralWidget(tabs)
        self._tabs = tabs

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # ── Данные ───────────────────────────────────────────────────
        data_menu: QMenu = menubar.addMenu("Данные")

        import_action = QAction("Импорт из Excel…", self)
        import_action.setStatusTip("Загрузить данные из файла .xlsx")
        import_action.triggered.connect(self._open_migration_dialog)
        data_menu.addAction(import_action)

        data_menu.addSeparator()

        export_report_action = QAction("Экспорт проблемных опросов…", self)
        export_report_action.setStatusTip("Сохранить отчёт о проблемных опросах в .md-файл")
        export_report_action.triggered.connect(self._export_report)
        data_menu.addAction(export_report_action)

        export_excel_action = QAction("Экспорт всех данных в Excel…", self)
        export_excel_action.setStatusTip("Выгрузить все таблицы базы в файл .xlsx")
        export_excel_action.triggered.connect(self._export_full_excel)
        data_menu.addAction(export_excel_action)

        data_menu.addSeparator()

        # ── Подменю: Резервные копии ──────────────────────────────────
        backup_menu: QMenu = data_menu.addMenu("Резервные копии")

        backup_action = QAction("Создать резервную копию", self)
        backup_action.setStatusTip("Сохранить копию базы данных в папку data/backups/")
        backup_action.triggered.connect(self._backup_db)
        backup_menu.addAction(backup_action)

        restore_action = QAction("Восстановить из копии…", self)
        restore_action.setStatusTip("Заменить базу данных файлом резервной копии")
        restore_action.triggered.connect(self._restore_db)
        backup_menu.addAction(restore_action)

        # ── Вид ──────────────────────────────────────────────────────
        view_menu: QMenu = menubar.addMenu("Вид")

        self._dark_action = QAction("Тёмная тема", self)
        self._dark_action.setCheckable(True)
        self._dark_action.setChecked(self._dark)
        self._dark_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(self._dark_action)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _toggle_theme(self, dark: bool) -> None:
        self._dark = dark
        self._apply_theme(dark)
        from services.config_store import load_config, save_config
        cfg = load_config()
        cfg["theme"] = "dark" if dark else "light"
        save_config(cfg)
        label = "тёмная" if dark else "светлая"
        self.statusBar().showMessage(f"Тема: {label}", 3000)
        log.info("Theme switched to %s", label)

    def _apply_theme(self, dark: bool) -> None:
        qss_name = "styles_dark.qss" if dark else "styles.qss"
        qss_path = _STYLES_DIR / qss_name
        qss = qss_path.read_text(encoding="utf-8") if qss_path.exists() else ""
        QApplication.instance().setStyleSheet(qss)
        self._analytics_widget.set_dark_theme(dark)

    # ------------------------------------------------------------------
    # Data actions
    # ------------------------------------------------------------------

    def _open_migration_dialog(self) -> None:
        from ui.migration_dialog import MigrationDialog
        dlg = MigrationDialog(self.session, parent=self)
        dlg.migration_done.connect(self._on_migration_done)
        dlg.exec()

    def _export_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить отчёт",
            "problematic_surveys.md",
            "Markdown (*.md);;Все файлы (*)",
        )
        if not path:
            return
        from services.export import export_to_file
        try:
            count = export_to_file(self.session, path)
            self.statusBar().showMessage(
                f"Экспортировано {count} проблемных опросов → {path}", 6000
            )
            log.info("Export: %d surveys → %s", count, path)
        except Exception as exc:
            log.exception("Export failed")
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))

    def _export_full_excel(self) -> None:
        """Export all database tables to a single Excel file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт всех данных в Excel",
            "surveys_export.xlsx",
            "Excel (*.xlsx);;Все файлы (*)",
        )
        if not path:
            return
        from services.excel_full_export import export_full_excel
        try:
            counts = export_full_excel(self.session, path)
            total = sum(counts.values())
            detail = ", ".join(f"{k}: {v}" for k, v in counts.items())
            self.statusBar().showMessage(
                f"Экспортировано {total} записей → {path}", 8000
            )
            QMessageBox.information(
                self,
                "Экспорт завершён",
                f"Файл сохранён:\n{path}\n\nЗаписей по листам:\n{detail}",
            )
            log.info("Full Excel export: %s → %s", counts, path)
        except Exception as exc:
            log.exception("Full Excel export failed")
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))

    # ------------------------------------------------------------------
    # Backup / Restore
    # ------------------------------------------------------------------

    def _backup_db(self) -> None:
        """Create a timestamped backup of the SQLite database."""
        from services.backup import create_backup
        try:
            dest = create_backup()
            size_kb = dest.stat().st_size / 1024
            self.statusBar().showMessage(
                f"Резервная копия сохранена: {dest.name} ({size_kb:.0f} KB)", 6000
            )
            QMessageBox.information(
                self,
                "Резервная копия создана",
                f"Файл сохранён:\n{dest}",
            )
            log.info("Backup created: %s", dest)
        except Exception as exc:
            log.exception("Backup failed")
            QMessageBox.critical(self, "Ошибка резервной копии", str(exc))

    def _restore_db(self) -> None:
        """Restore database from a backup file chosen by the user."""
        from services.backup import BACKUP_DIR, restore_backup
        from database import SessionLocal

        # Default dir for the file dialog — open backups folder if it exists
        start_dir = str(BACKUP_DIR) if BACKUP_DIR.exists() else "data"

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать резервную копию",
            start_dir,
            "SQLite database (*.db);;Все файлы (*)",
        )
        if not path:
            return

        reply = QMessageBox.warning(
            self,
            "Восстановление базы данных",
            f"Текущая база будет заменена файлом:\n{path}\n\n"
            "Все несохранённые изменения будут потеряны.\n"
            "Перед заменой автоматически сохранится снимок текущей базы.\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            # Close current session before replacing the file
            self.session.close()

            restore_backup(Path(path))

            # Reopen session and rebind to all widgets
            new_session: Session = SessionLocal()
            self.session = new_session
            for widget in (
                self._clients_widget,
                self._employees_widget,
                self._surveys_widget,
                self._complaints_widget,
                self._analytics_widget,
                self._ai_widget,
            ):
                widget._session = new_session

            # Reload all data
            self._clients_widget.load_data()
            self._employees_widget.load_data()
            self._surveys_widget.load_data()
            self._complaints_widget.load_data()
            self._analytics_widget.load_data()

            self.statusBar().showMessage("База данных восстановлена.", 6000)
            QMessageBox.information(
                self,
                "Восстановление завершено",
                f"База данных успешно восстановлена из:\n{path}",
            )
            log.info("Database restored from: %s", path)
        except Exception as exc:
            log.exception("Restore failed")
            QMessageBox.critical(self, "Ошибка восстановления", str(exc))

    def _on_migration_done(self) -> None:
        log.info("Migration done — refreshing tabs")
        self._clients_widget.load_data()
        self._surveys_widget.load_data()
        self._complaints_widget.load_data()
        self._analytics_widget.load_data()
        self.statusBar().showMessage("Данные успешно импортированы.", 5000)
