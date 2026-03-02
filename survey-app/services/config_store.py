"""
Lightweight JSON config store.

Persists user preferences (API key, model selection) between sessions.
File lives at data/config.json alongside the SQLite database.
"""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_CONFIG_PATH = Path("data/config.json")

_DEFAULTS: dict = {
    "api_key": "",
    "model": "openai/gpt-4o-mini",
    "theme": "light",
    "custom_models": [],   # list of {"name": str, "id": str}
}


def load_config() -> dict:
    """Return config dict. Missing keys are filled with defaults."""
    if not _CONFIG_PATH.exists():
        log.debug("No config file found, using defaults")
        return dict(_DEFAULTS)
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        result = {**_DEFAULTS, **data}
        log.debug("Config loaded: model=%s, api_key_set=%s",
                  result.get("model"), bool(result.get("api_key")))
        return result
    except Exception:
        log.exception("Failed to load config, using defaults")
        return dict(_DEFAULTS)


def save_config(data: dict) -> None:
    """Persist config dict to disk."""
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.debug("Config saved: model=%s", data.get("model"))
    except Exception:
        log.exception("Failed to save config")
