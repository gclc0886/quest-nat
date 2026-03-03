"""
Utility: resizable columns with persistence.

Usage:
    from ui.table_utils import setup_resizable_columns
    setup_resizable_columns(self._table, "clients", [200, 160, 100, ...])

Column widths are stored in  data/column_widths.json  so they survive
application restarts. Each table is identified by a unique string key.
"""
import json
import logging
from pathlib import Path

from PyQt6.QtWidgets import QHeaderView, QTableWidget

log = logging.getLogger(__name__)

_WIDTHS_PATH = Path("data/column_widths.json")


def _load_all() -> dict:
    try:
        if _WIDTHS_PATH.exists():
            return json.loads(_WIDTHS_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.exception("Failed to load column_widths.json")
    return {}


def _save_all(data: dict) -> None:
    try:
        _WIDTHS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _WIDTHS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.exception("Failed to save column_widths.json")


def setup_resizable_columns(
    table: QTableWidget,
    key: str,
    defaults: list[int],
) -> None:
    """
    Make every column of *table* interactively resizable and persist widths.

    :param table:    The QTableWidget to configure.
    :param key:      Unique identifier used as the JSON key (e.g. "clients").
    :param defaults: Default column widths in pixels, one per column.
    """
    n = table.columnCount()
    hh = table.horizontalHeader()

    # All columns become draggable
    for col in range(n):
        hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)

    # Restore saved widths or fall back to defaults
    saved = _load_all().get(key)
    widths = saved if (saved and len(saved) == n) else defaults
    for col, w in enumerate(widths):
        table.setColumnWidth(col, w)

    # Persist on every resize
    def _on_resized(_col: int, _old: int, _new: int) -> None:
        current = [table.columnWidth(c) for c in range(n)]
        data = _load_all()
        data[key] = current
        _save_all(data)

    hh.sectionResized.connect(_on_resized)
