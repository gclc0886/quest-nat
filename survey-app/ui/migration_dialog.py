"""
Migration dialog — imports data from an Excel file (.xlsx) into the database.

Flow:
  1. User selects .xlsx file via file picker
  2. Clicks "Начать миграцию"
  3. QThread runs import_excel.run_migration() with progress callbacks
  4. Progress bar updates during migration
  5. Result report shown in text area
  6. Emits migration_done signal so main window can refresh tables
"""
import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QTextEdit, QVBoxLayout,
)
from sqlalchemy.orm import Session

from migration.import_excel import MigrationResult, run_migration

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker thread — keeps UI responsive during migration
# ---------------------------------------------------------------------------

class _MigrationWorker(QThread):
    progress = pyqtSignal(int, int)          # (current, total)
    finished = pyqtSignal(MigrationResult)
    error = pyqtSignal(str)

    def __init__(self, filepath: str, session: Session):
        super().__init__()
        self._filepath = filepath
        self._session = session

    def run(self) -> None:
        try:
            result = run_migration(
                self._filepath,
                self._session,
                progress_callback=lambda cur, tot: self.progress.emit(cur, tot),
            )
            self.finished.emit(result)
        except Exception as exc:
            log.exception("Migration worker crashed")
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class MigrationDialog(QDialog):
    """Dialog for importing data from Excel into the database."""

    migration_done = pyqtSignal()  # emitted after successful import

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session = session
        self._worker: _MigrationWorker | None = None
        self._build_ui()
        self.setWindowTitle("Импорт данных из Excel")
        self.setMinimumWidth(560)
        self.resize(600, 460)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # --- File selection row ---
        file_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Путь к файлу .xlsx…")
        self._path_edit.setReadOnly(True)

        browse_btn = QPushButton("Выбрать файл…")
        browse_btn.clicked.connect(self._browse)

        file_row.addWidget(QLabel("Файл:"))
        file_row.addWidget(self._path_edit, stretch=1)
        file_row.addWidget(browse_btn)
        root.addLayout(file_row)

        # --- Info label ---
        info = QLabel(
            "Миграция создаёт клиентов и опросы из файла Excel.\n"
            "Повторный запуск безопасен — существующие клиенты будут пропущены."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(info)

        # --- Progress bar ---
        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # --- Result text area ---
        self._report = QTextEdit()
        self._report.setReadOnly(True)
        self._report.setPlaceholderText("Здесь появится отчёт о результатах миграции…")
        self._report.setMinimumHeight(200)
        root.addWidget(self._report)

        # --- Buttons ---
        self._run_btn = QPushButton("Начать миграцию")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._run_migration)

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._run_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать файл Excel",
            "",
            "Excel файлы (*.xlsx *.xls);;Все файлы (*)",
        )
        if path:
            self._path_edit.setText(path)
            self._run_btn.setEnabled(True)
            self._report.clear()
            log.info("Selected file: %s", path)

    def _run_migration(self) -> None:
        filepath = self._path_edit.text().strip()
        if not filepath:
            return

        self._run_btn.setEnabled(False)
        self._report.clear()
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._report.setPlaceholderText("Идёт миграция…")

        self._worker = _MigrationWorker(filepath, self._session)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        log.info("Migration worker started for: %s", filepath)

    def _on_progress(self, current: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(current)
        self._progress.setFormat(f"{current} / {total}")

    def _on_finished(self, result: MigrationResult) -> None:
        self._progress.setValue(self._progress.maximum())
        self._run_btn.setEnabled(True)

        report_text = result.as_report()
        self._report.setPlaceholderText("")
        self._report.setPlainText(report_text)

        log.info("Migration finished: clients=%d surveys=%d errors=%d",
                 result.clients_created, result.surveys_created, len(result.errors))

        if result.clients_created > 0 or result.surveys_created > 0:
            self.migration_done.emit()

        if result.errors:
            QMessageBox.warning(
                self, "Миграция завершена с ошибками",
                f"Импортировано {result.clients_created} клиентов и "
                f"{result.surveys_created} опросов.\n"
                f"Ошибок: {len(result.errors)}. Подробности — в отчёте.",
            )
        else:
            QMessageBox.information(
                self, "Миграция завершена",
                f"Успешно импортировано:\n"
                f"  Клиентов: {result.clients_created}\n"
                f"  Опросов:  {result.surveys_created}\n"
                f"  Пропущено (уже существуют): {result.clients_skipped}",
            )

    def _on_error(self, message: str) -> None:
        self._progress.setVisible(False)
        self._run_btn.setEnabled(True)
        self._report.setPlainText(f"Критическая ошибка:\n{message}")
        log.error("Migration dialog: critical error: %s", message)
        QMessageBox.critical(self, "Ошибка миграции", message)
