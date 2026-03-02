"""
AI chat service — OpenRouter API via httpx with SSE streaming.

Usage::

    worker = AIChatWorker(api_key, model, messages)
    worker.chunk_received.connect(on_chunk)   # str — incremental token
    worker.finished.connect(on_done)          # emitted when stream ends
    worker.error_occurred.connect(on_error)   # str — error message
    worker.start()
    # later:
    worker.abort()
"""
import json
import logging

import httpx
from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_HTTP_REFERER   = "https://localhost/survey-app"
_APP_TITLE      = "Survey App"
_TIMEOUT        = 90  # seconds

# Models shown in the UI dropdown (display name → model id)
AVAILABLE_MODELS: list[tuple[str, str]] = [
    ("GPT-4o mini (OpenAI)",                   "openai/gpt-4o-mini"),
    ("GPT-4o (OpenAI)",                         "openai/gpt-4o"),
    ("Claude 3.5 Haiku (Anthropic)",            "anthropic/claude-3-5-haiku"),
    ("Claude 3.5 Sonnet (Anthropic)",           "anthropic/claude-3-5-sonnet"),
    ("Gemini 2.0 Flash (Google)",               "google/gemini-2.0-flash-001"),
    ("Gemini 2.0 Flash Lite (Google · бесплатно)", "google/gemini-2.0-flash-lite:free"),
    ("Llama 3.3 70B (Meta · бесплатно)",        "meta-llama/llama-3.3-70b-instruct:free"),
    ("DeepSeek R1 (бесплатно)",                 "deepseek/deepseek-r1:free"),
    ("DeepSeek V3 (бесплатно)",                 "deepseek/deepseek-chat:free"),
    ("Mistral Small 3.1 (бесплатно)",           "mistralai/mistral-small-3.1-24b-instruct:free"),
]


class AIChatWorker(QThread):
    """
    QThread that streams a single chat completion from OpenRouter.

    Signals
    -------
    chunk_received(str)   – incremental content token
    finished()            – stream ended successfully
    error_occurred(str)   – error description
    """

    chunk_received = pyqtSignal(str)
    finished       = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        api_key: str,
        model: str,
        messages: list[dict],
        parent=None,
    ):
        super().__init__(parent)
        self._api_key  = api_key
        self._model    = model
        self._messages = messages
        self._abort    = False

    def abort(self) -> None:
        """Signal the worker to stop streaming after the current chunk."""
        log.debug("AIChatWorker: abort requested")
        self._abort = True

    # ------------------------------------------------------------------

    def run(self) -> None:
        log.info("AIChatWorker starting: model=%s, messages=%d",
                 self._model, len(self._messages))

        headers = {
            "Authorization":  f"Bearer {self._api_key}",
            "Content-Type":   "application/json",
            "HTTP-Referer":   _HTTP_REFERER,
            "X-Title":        _APP_TITLE,
        }
        payload = {
            "model":    self._model,
            "messages": self._messages,
            "stream":   True,
        }

        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                with client.stream(
                    "POST", _OPENROUTER_URL,
                    headers=headers, json=payload,
                ) as response:
                    if response.status_code != 200:
                        body = response.read().decode(errors="replace")
                        log.error("OpenRouter HTTP %s: %s", response.status_code, body)
                        if response.status_code == 429:
                            self.error_occurred.emit(
                                "Превышен лимит запросов у провайдера (429). "
                                "Попробуйте другую модель или подождите несколько минут."
                            )
                        elif response.status_code == 404:
                            self.error_occurred.emit(
                                "Модель не найдена (404). "
                                "Выберите другую модель в настройках."
                            )
                        elif response.status_code == 401:
                            self.error_occurred.emit(
                                "Неверный API ключ (401). "
                                "Проверьте ключ в настройках."
                            )
                        else:
                            self.error_occurred.emit(
                                f"Ошибка сервера {response.status_code}:\n{body}"
                            )
                        return

                    for raw_line in response.iter_lines():
                        if self._abort:
                            log.debug("AIChatWorker: aborted mid-stream")
                            break
                        if not raw_line.startswith("data: "):
                            continue
                        data_str = raw_line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            content = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if content:
                                self.chunk_received.emit(content)
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue

            self.finished.emit()
            log.info("AIChatWorker: stream finished")

        except httpx.TimeoutException:
            msg = "Превышен таймаут запроса к API."
            log.warning("AIChatWorker: %s", msg)
            self.error_occurred.emit(msg)
        except httpx.ConnectError as exc:
            msg = f"Нет подключения к серверу: {exc}"
            log.warning("AIChatWorker: %s", msg)
            self.error_occurred.emit(msg)
        except Exception as exc:
            log.exception("AIChatWorker: unexpected error")
            self.error_occurred.emit(str(exc))
