from __future__ import annotations
import json, os

import json
import os

from mutants.state import state_path

PATH = state_path("runtime", "trace.json")


def _load() -> dict:
    try:
        with PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save(d: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_name(PATH.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, PATH)


def set_flag(name: str, value: bool) -> None:
    d = _load()
    d[name] = bool(value)
    _save(d)


def get_flag(name: str) -> bool:
    return bool(_load().get(name, False))


# Convenience helpers for common flags


def is_move_trace_enabled() -> bool:
    """Return True if move tracing is enabled."""
    return get_flag("move")


def set_move_trace_enabled(val: bool) -> None:
    """Enable or disable move tracing."""
    set_flag("move", bool(val))


def is_ui_trace_enabled() -> bool:
    """Return True if UI tracing is enabled."""
    return get_flag("ui")


def set_ui_trace_enabled(val: bool) -> None:
    """Enable or disable UI tracing."""
    set_flag("ui", bool(val))
