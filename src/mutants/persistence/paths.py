"""Centralized filesystem paths for player template and save data."""
from __future__ import annotations

from pathlib import Path


STATE_ROOT = Path("state")


TEMPLATE_PATH = STATE_ROOT / "playerlivestate.json"
SAVE_PATH = STATE_ROOT / "savegame.json"


def ensure_state_root() -> None:
    """Ensure the state root directory exists."""
    STATE_ROOT.mkdir(parents=True, exist_ok=True)

