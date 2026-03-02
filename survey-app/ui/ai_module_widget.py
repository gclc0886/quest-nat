"""AI chat tab — OpenRouter chat with context loading from survey data."""
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPushButton, QSizePolicy, QSplitter,
    QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)
from sqlalchemy.orm import Session

from services.ai_service import AVAILABLE_MODELS, AIChatWorker
from services.config_store import load_config, save_config
from services.export import build_unsatisfied_report

log = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "Ты — аналитический ассистент детского коррекционного центра. "
    "Помогаешь анализировать обратную связь от родителей, выявлять проблемные паттерны "
    "и формулировать рекомендации для улучшения работы центра. "
    "Отвечай кратко, по делу, на русском языке."
)

_USER_COLOR = "#0d6efd"
_ASST_COLOR = "#212529"
_ERR_COLOR  = "#dc3545"

_AUTO_ANALYSIS_PROMPT = (
    "Проанализируй загруженные данные о проблемных опросах и подготовь структурированный отчёт:\n\n"
    "1. **Общая картина** — сколько проблемных случаев, какие типы жалоб преобладают.\n"
    "2. **Жалобы на сотрудников** — кто упоминается, в чём суть претензий.\n"
    "3. **Жалобы на условия** — что конкретно не устраивает клиентов.\n"
    "4. **Неулаженные ситуации** — есть ли затяжные или повторяющиеся проблемы.\n"
    "5. **Рекомендации** — 3–5 конкретных действий для улучшения ситуации.\n\n"
    "Если данных мало — скажи об этом и дай рекомендации по сбору обратной связи."
)


class _ManageModelsDialog(QDialog):
    """Dialog for adding and removing user-defined OpenRouter models."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Пользовательские модели")
        self.setMinimumWidth(500)
        self.setMinimumHeight(340)
        self._build_ui()
        self._reload_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Existing custom models
        list_g = QGroupBox("Добавленные модели")
        list_gl = QVBoxLayout(list_g)
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        list_gl.addWidget(self._list)
        layout.addWidget(list_g)

        # Add-model form
        add_g = QGroupBox("Добавить новую модель")
        add_gl = QFormLayout(add_g)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("например: GPT-4o Turbo (OpenAI)")
        self._id_edit = QLineEdit()
        self._id_edit.setPlaceholderText("например: openai/gpt-4o-turbo или provider/model:free")
        add_gl.addRow("Название:", self._name_edit)
        add_gl.addRow("ID модели:", self._id_edit)
        layout.addWidget(add_g)

        # Buttons
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Добавить")
        add_btn.clicked.connect(self._add)
        del_btn = QPushButton("Удалить выбранную")
        del_btn.clicked.connect(self._delete)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.accept)
        btn_row.addWidget(close_box)
        layout.addLayout(btn_row)

    def _reload_list(self) -> None:
        self._list.clear()
        for m in load_config().get("custom_models", []):
            self._list.addItem(f"{m['name']}   │   {m['id']}")

    def _add(self) -> None:
        name = self._name_edit.text().strip()
        model_id = self._id_edit.text().strip()
        if not name or not model_id:
            QMessageBox.warning(self, "Ошибка", "Укажите название и ID модели.")
            return
        cfg = load_config()
        models: list[dict] = cfg.get("custom_models", [])
        if any(m["id"] == model_id for m in models):
            QMessageBox.warning(self, "Дубликат",
                                f"Модель «{model_id}» уже добавлена.")
            return
        models.append({"name": name, "id": model_id})
        cfg["custom_models"] = models
        save_config(cfg)
        self._name_edit.clear()
        self._id_edit.clear()
        self._reload_list()
        log.info("Custom model added: %s (%s)", name, model_id)

    def _delete(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            QMessageBox.information(self, "Удаление", "Выберите модель из списка.")
            return
        cfg = load_config()
        models: list[dict] = cfg.get("custom_models", [])
        if row < len(models):
            removed = models.pop(row)
            cfg["custom_models"] = models
            save_config(cfg)
            self._reload_list()
            log.info("Custom model removed: %s (%s)", removed["name"], removed["id"])


class AiModuleWidget(QWidget):
    """AI chat widget with API settings, context loader, and streaming chat."""

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session = session
        self._history: list[dict] = []   # [{role, content}, ...]
        self._worker: AIChatWorker | None = None
        self._context_text: str = ""     # loaded from export service
        self._build_ui()
        self._load_settings()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ── Settings row ─────────────────────────────────────────────
        settings_g = QGroupBox("Настройки API")
        settings_l = QHBoxLayout(settings_g)

        settings_l.addWidget(QLabel("API ключ:"))
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("sk-or-…")
        self._api_key_edit.setMinimumWidth(260)
        settings_l.addWidget(self._api_key_edit, stretch=1)

        settings_l.addWidget(QLabel("Модель:"))
        self._model_cb = QComboBox()
        self._model_cb.setMinimumWidth(220)
        settings_l.addWidget(self._model_cb)

        manage_btn = QPushButton("+ Модели")
        manage_btn.setFixedWidth(90)
        manage_btn.setToolTip("Добавить или удалить пользовательские модели OpenRouter")
        manage_btn.clicked.connect(self._manage_models)
        settings_l.addWidget(manage_btn)

        save_btn = QPushButton("Сохранить")
        save_btn.setFixedWidth(100)
        save_btn.clicked.connect(self._save_settings)
        settings_l.addWidget(save_btn)

        root.addWidget(settings_g)

        # ── Splitter: left=controls, right=chat ──────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 4, 0)

        # System prompt
        prompt_g = QGroupBox("Системный промпт")
        prompt_gl = QVBoxLayout(prompt_g)
        self._system_edit = QTextEdit()
        self._system_edit.setPlainText(_DEFAULT_SYSTEM_PROMPT)
        self._system_edit.setFixedHeight(110)
        prompt_gl.addWidget(self._system_edit)
        left_l.addWidget(prompt_g)

        # Context loader
        ctx_g = QGroupBox("Контекст из базы")
        ctx_gl = QVBoxLayout(ctx_g)
        load_ctx_btn = QPushButton("Загрузить проблемные опросы")
        load_ctx_btn.clicked.connect(self._load_context)
        clear_ctx_btn = QPushButton("Очистить контекст")
        clear_ctx_btn.clicked.connect(self._clear_context)
        self._ctx_lbl = QLabel("Контекст не загружен")
        self._ctx_lbl.setWordWrap(True)
        self._ctx_lbl.setStyleSheet("color: #888; font-size: 11px;")
        ctx_gl.addWidget(load_ctx_btn)
        ctx_gl.addWidget(clear_ctx_btn)
        ctx_gl.addWidget(self._ctx_lbl)

        self._auto_btn = QPushButton("Запустить авто-анализ")
        self._auto_btn.setToolTip(
            "Загружает проблемные опросы (если не загружены) "
            "и отправляет подготовленный запрос на анализ"
        )
        self._auto_btn.setStyleSheet(
            "QPushButton { background-color: #198754; }"
            "QPushButton:hover { background-color: #157347; }"
            "QPushButton:pressed { background-color: #146c43; }"
            "QPushButton:disabled { background-color: #adb5bd; }"
        )
        self._auto_btn.clicked.connect(self._run_auto_analysis)
        ctx_gl.addWidget(self._auto_btn)

        left_l.addWidget(ctx_g)

        # Chat controls
        ctrl_g = QGroupBox("Управление чатом")
        ctrl_gl = QVBoxLayout(ctrl_g)
        clear_chat_btn = QPushButton("Очистить историю")
        clear_chat_btn.clicked.connect(self._clear_chat)
        ctrl_gl.addWidget(clear_chat_btn)
        left_l.addWidget(ctrl_g)

        left_l.addStretch()
        splitter.addWidget(left)

        # Right panel — chat
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(4, 0, 0, 0)

        self._chat_browser = QTextBrowser()
        self._chat_browser.setOpenExternalLinks(False)
        mono = QFont("Segoe UI", 10)
        self._chat_browser.setFont(mono)
        right_l.addWidget(self._chat_browser, stretch=1)

        # Input row
        input_row = QHBoxLayout()
        self._input_edit = QLineEdit()
        self._input_edit.setPlaceholderText("Введите сообщение и нажмите Enter…")
        self._input_edit.returnPressed.connect(self._send)
        self._input_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._send_btn = QPushButton("Отправить")
        self._send_btn.setFixedWidth(110)
        self._send_btn.clicked.connect(self._send)
        self._stop_btn = QPushButton("Стоп")
        self._stop_btn.setFixedWidth(70)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        input_row.addWidget(self._input_edit)
        input_row.addWidget(self._send_btn)
        input_row.addWidget(self._stop_btn)
        right_l.addLayout(input_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _rebuild_model_cb(self, select_id: str | None = None) -> None:
        """Repopulate the model combobox (built-in + user-defined)."""
        cfg = load_config()
        current_id = select_id or self._model_cb.currentData()
        self._model_cb.clear()
        for display, model_id in AVAILABLE_MODELS:
            self._model_cb.addItem(display, model_id)
        custom: list[dict] = cfg.get("custom_models", [])
        if custom:
            self._model_cb.insertSeparator(self._model_cb.count())
            for m in custom:
                self._model_cb.addItem(f"★ {m['name']}", m["id"])
        # Restore selection
        for i in range(self._model_cb.count()):
            if self._model_cb.itemData(i) == current_id:
                self._model_cb.setCurrentIndex(i)
                break

    def _load_settings(self) -> None:
        cfg = load_config()
        self._api_key_edit.setText(cfg.get("api_key", ""))
        model_id = cfg.get("model", AVAILABLE_MODELS[0][1])
        self._rebuild_model_cb(select_id=model_id)
        log.debug("AI settings loaded: model=%s", model_id)

    def _manage_models(self) -> None:
        dlg = _ManageModelsDialog(parent=self)
        dlg.exec()
        # Rebuild dropdown after user makes changes
        self._rebuild_model_cb()

    def _save_settings(self) -> None:
        cfg = load_config()
        cfg["api_key"] = self._api_key_edit.text().strip()
        cfg["model"]   = self._model_cb.currentData()
        save_config(cfg)
        self.window().statusBar().showMessage("Настройки AI сохранены.", 3000)
        log.info("AI settings saved: model=%s", cfg["model"])

    # ------------------------------------------------------------------
    # Context loading
    # ------------------------------------------------------------------

    def _load_context(self) -> None:
        report = build_unsatisfied_report(self._session)
        self._context_text = report
        survey_count = report.count("### Опрос:")
        if survey_count:
            self._ctx_lbl.setText(f"Загружено: {survey_count} проблемных опросов")
            self._ctx_lbl.setStyleSheet("color: #28a745; font-size: 11px;")
        else:
            self._ctx_lbl.setText("Проблемных опросов не найдено")
            self._ctx_lbl.setStyleSheet("color: #888; font-size: 11px;")
        log.info("Context loaded: %d problem surveys", survey_count)

    def _clear_context(self) -> None:
        self._context_text = ""
        self._ctx_lbl.setText("Контекст не загружен")
        self._ctx_lbl.setStyleSheet("color: #888; font-size: 11px;")
        log.debug("Context cleared")

    def _run_auto_analysis(self) -> None:
        """Load context if needed, then send a pre-built analysis prompt."""
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "Занято",
                                    "Дождитесь завершения текущего ответа.")
            return
        # Auto-load context if not yet loaded
        if not self._context_text:
            self._load_context()
        if not self._context_text:
            QMessageBox.information(self, "Нет данных",
                                    "Проблемных опросов не найдено — анализировать нечего.")
            return
        self._input_edit.setText(_AUTO_ANALYSIS_PROMPT)
        self._send()
        log.info("Auto-analysis prompt sent")

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        base = self._system_edit.toPlainText().strip()
        if self._context_text:
            return f"{base}\n\n---\n\nДАННЫЕ О ПРОБЛЕМНЫХ ОПРОСАХ:\n\n{self._context_text}"
        return base

    def _send(self) -> None:
        text = self._input_edit.text().strip()
        if not text:
            return

        api_key = self._api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "API ключ не задан",
                                "Введите API ключ OpenRouter и нажмите «Сохранить».")
            return

        model = self._model_cb.currentData()
        self._input_edit.clear()

        # Append user message to history and display
        self._history.append({"role": "user", "content": text})
        self._append_message("user", text)

        # Build full messages list for API
        system_prompt = self._build_system_prompt()
        messages = [{"role": "system", "content": system_prompt}] + self._history

        # Start worker
        self._worker = AIChatWorker(api_key, model, messages, parent=self)
        self._worker.chunk_received.connect(self._on_chunk)
        self._worker.finished.connect(self._on_finished)
        self._worker.error_occurred.connect(self._on_error)

        self._send_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._input_edit.setEnabled(False)

        # Prepare assistant message placeholder in display
        self._append_message("assistant", "")
        self._asst_response_buf = ""

        log.info("Sending message to %s (history=%d)", model, len(self._history))
        self._worker.start()

    def _stop(self) -> None:
        if self._worker:
            self._worker.abort()
        log.debug("User requested stop")

    def _on_chunk(self, token: str) -> None:
        self._asst_response_buf += token
        # Update last paragraph in the browser (the assistant placeholder)
        cursor = self._chat_browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(token)
        self._chat_browser.setTextCursor(cursor)
        self._chat_browser.ensureCursorVisible()

    def _on_finished(self) -> None:
        # Save completed assistant message to history
        if self._asst_response_buf:
            self._history.append({"role": "assistant", "content": self._asst_response_buf})
        self._asst_response_buf = ""
        self._set_input_state(enabled=True)
        self._append_divider()
        log.info("Assistant response complete (%d chars)", len(self._history[-1]["content"])
                 if self._history else 0)

    def _on_error(self, msg: str) -> None:
        self._asst_response_buf = ""
        self._set_input_state(enabled=True)
        self._append_message("error", msg)
        log.error("AI error: %s", msg)

    def _set_input_state(self, *, enabled: bool) -> None:
        self._send_btn.setEnabled(enabled)
        self._stop_btn.setEnabled(not enabled)
        self._input_edit.setEnabled(enabled)
        self._auto_btn.setEnabled(enabled)
        if enabled:
            self._input_edit.setFocus()

    # ------------------------------------------------------------------
    # Chat display helpers
    # ------------------------------------------------------------------

    def _append_message(self, role: str, text: str) -> None:
        cursor = self._chat_browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if role == "user":
            label = f'<p><b><span style="color:{_USER_COLOR}">Вы:</span></b> '
            cursor.insertHtml(label + _esc(text) + "</p>")
        elif role == "assistant":
            cursor.insertHtml(
                f'<p><b><span style="color:{_ASST_COLOR}">AI:</span></b> '
            )
        elif role == "error":
            cursor.insertHtml(
                f'<p><span style="color:{_ERR_COLOR}">⚠ Ошибка: {_esc(text)}</span></p>'
            )

        self._chat_browser.setTextCursor(cursor)
        self._chat_browser.ensureCursorVisible()

    def _append_divider(self) -> None:
        cursor = self._chat_browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml("<hr/>")
        self._chat_browser.setTextCursor(cursor)

    def _clear_chat(self) -> None:
        self._history.clear()
        self._chat_browser.clear()
        self._asst_response_buf = ""
        log.debug("Chat history cleared")


def _esc(text: str) -> str:
    """Minimal HTML escaping for user-supplied strings."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
