from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mutants.constants import CLASS_ORDER
from mutants.ui import class_menu
from mutants.services import player_state


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"feedback_bus": DummyBus()}


def test_class_menu_renders_in_order(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    raw_state = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2000, 0, 0], "level": 3},
            {"id": "player_thief_2", "class": "Thief", "pos": [2005, 1, 1], "level": 5},
            {"id": "player_priest", "class": "Priest", "pos": [2001, 0, 0], "level": 2},
            {"id": "player_wizard", "class": "Wizard", "pos": [2002, 2, 2], "level": 4},
        ],
        "active_id": "player_thief_2",
        "ions_by_class": {},
    }

    def _fake_load_state() -> dict[str, Any]:
        return player_state.ensure_class_profiles(copy.deepcopy(raw_state))

    monkeypatch.setattr(player_state, "load_state", _fake_load_state)

    class_menu.render_menu(ctx)

    lines = [msg for channel, msg in ctx["feedback_bus"].messages if channel == "SYSTEM/OK"]
    header_lines = [line for line in lines if line.startswith(" ")][: len(CLASS_ORDER)]
    assert len(header_lines) == len(CLASS_ORDER)
    for idx, class_name in enumerate(CLASS_ORDER, start=1):
        assert f"{idx:>2}. Mutant {class_name:<7}" in header_lines[idx - 1]
