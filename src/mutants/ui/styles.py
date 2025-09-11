"""Token definitions and helpers for styling the UI."""
from __future__ import annotations

from typing import Dict, List, Tuple

Segment = Tuple[str, str]

# Token names
HEADER = "HEADER"
COMPASS_LABEL = "COMPASS_LABEL"
COORDS = "COORDS"
DIR = "DIR"
DESC_CONT = "DESC_CONT"
DESC_TERRAIN = "DESC_TERRAIN"
DESC_BOUNDARY = "DESC_BOUNDARY"
DESC_GATE_OPEN = "DESC_GATE_OPEN"
DESC_GATE_CLOSED = "DESC_GATE_CLOSED"
DESC_GATE_LOCKED = "DESC_GATE_LOCKED"
LABEL = "LABEL"
ITEM = "ITEM"
MONSTER = "MONSTER"
SHADOWS_LABEL = "SHADOWS_LABEL"
FEED_SYS_OK = "FEED_SYS_OK"
FEED_SYS_WARN = "FEED_SYS_WARN"
FEED_SYS_ERR = "FEED_SYS_ERR"
FEED_MOVE = "FEED_MOVE"
FEED_BLOCK = "FEED_BLOCK"
FEED_COMBAT = "FEED_COMBAT"
FEED_CRIT = "FEED_CRIT"
FEED_TAUNT = "FEED_TAUNT"
FEED_LOOT = "FEED_LOOT"
FEED_SPELL = "FEED_SPELL"
FEED_DEBUG = "FEED_DEBUG"
RESET = "RESET"


def resolve_segments(segments: List[Segment], palette: Dict[str, str]) -> str:
    """Resolve segments into an ANSI string using *palette*."""
    pieces: List[str] = []
    reset = palette.get(RESET, "\x1b[0m")
    for token, text in segments:
        color = palette.get(token, "")
        if color:
            pieces.append(f"{color}{text}{reset}")
        else:
            pieces.append(text)
    return "".join(pieces)


def tagged_string(segments: List[Segment]) -> str:
    """Convert segments into a debug string with tags."""
    out: List[str] = []
    for token, text in segments:
        if token:
            out.append(f"<{token}>{text}</{token}>")
        else:
            out.append(text)
    return "".join(out)

from typing import Optional
import json
import os

# Back-compat: add group-aware color resolver without removing existing APIs.
_COLORS_CACHE: Optional[Dict[str, str]] = None
_DEFAULT_COLOR: str = "white"
_COLOR_FILE_ENV = "MUTANTS_UI_COLORS_PATH"  # optional override via env
_COLORS_PATH_OVERRIDE: Optional[str] = None  # programmatic override via theme
_ANSI_ENABLED: bool = True  # allow theme to disable ANSI for clean transcripts


def _colors_path() -> str:
    # 1) explicit programmatic override (theme)
    if _COLORS_PATH_OVERRIDE:
        return _COLORS_PATH_OVERRIDE
    # 2) environment
    p = os.environ.get(_COLOR_FILE_ENV)
    if p:
        return p
    # 3) default location
    return os.path.join(os.getcwd(), "state", "ui", "colors.json")


def _load_colors_map() -> Dict[str, str]:
    global _COLORS_CACHE, _DEFAULT_COLOR
    if _COLORS_CACHE is not None:
        return _COLORS_CACHE
    path = _colors_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _DEFAULT_COLOR = data.get("defaults", "white")
        mapping = data.get("map", {})
        _COLORS_CACHE = {str(k): str(v) for (k, v) in mapping.items()}
        return _COLORS_CACHE
    except FileNotFoundError:
        _COLORS_CACHE = {}
        _DEFAULT_COLOR = "white"
        return _COLORS_CACHE


def set_colors_map_path(path: Optional[str]) -> None:
    """
    Programmatically override the colors.json path (used by theme switching).
    Pass None to clear the override and fall back to env/defaults.
    """
    global _COLORS_PATH_OVERRIDE, _COLORS_CACHE
    _COLORS_PATH_OVERRIDE = path
    _COLORS_CACHE = None  # force reload on next resolve


def reload_colors_map() -> None:
    """Drop cache and reload immediately (useful after set_colors_map_path)."""
    global _COLORS_CACHE
    _COLORS_CACHE = None
    _ = _load_colors_map()


def set_ansi_enabled(enabled: bool) -> None:
    """Enable/disable ANSI coloring globally (themes can toggle this)."""
    global _ANSI_ENABLED
    _ANSI_ENABLED = bool(enabled)


def resolve_color_for_group(group: Optional[str]) -> str:
    """Resolve a color name for a semantic UI group with dotted fallback."""
    if not group:
        return _DEFAULT_COLOR
    m = _load_colors_map()
    if group in m:
        return m[group]
    parts = group.split(".")
    while len(parts) > 1:
        parts = parts[:-1]
        wildcard = ".".join(parts) + ".*"
        if wildcard in m:
            return m[wildcard]
    return _DEFAULT_COLOR


_COLOR_NAME_TO_ANSI = {
    "black": "\x1b[30m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "white": "\x1b[37m",
}


def _apply_color_name(text: str, color_name: str) -> str:
    color = _COLOR_NAME_TO_ANSI.get(color_name.lower())
    reset = "\x1b[0m"
    if color:
        return f"{color}{text}{reset}"
    return text


def colorize_text(text: str, *, group: Optional[str] = None, color: Optional[str] = None) -> str:
    # If ANSI is globally disabled, return text unchanged.
    if not _ANSI_ENABLED:
        return text
    color_name = color or resolve_color_for_group(group)
    try:
        return _apply_color_name(text, color_name)
    except Exception:
        return text

