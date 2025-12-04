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


def test_class_menu_uses_canonical_state(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    canonical_store = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2000, 0, 0], "level": 1},
            {"id": "player_priest", "class": "Priest", "pos": [2000, 0, 0], "level": 1},
            {"id": "player_wizard", "class": "Wizard", "pos": [2000, 0, 0], "level": 1},
            {"id": "player_spy", "class": "Spy", "pos": [2000, 0, 0], "level": 1},
            {"id": "player_elite", "class": "Elite", "pos": [2000, 0, 0], "level": 1},
        ],
        "active_id": "player_thief",
        "ions_by_class": {},
    }

    def _fake_load_state() -> dict[str, Any]:
        return player_state.ensure_class_profiles(copy.deepcopy(canonical_store))

    def _fake_save_state(state: dict[str, Any]) -> None:
        canonical_store.clear()
        canonical_store.update(copy.deepcopy(state))

    monkeypatch.setattr(player_state, "load_state", _fake_load_state)
    monkeypatch.setattr(player_state, "save_state", _fake_save_state)

    class_menu.render_menu(ctx)
    first_lines = [msg for channel, msg in ctx["feedback_bus"].messages if channel == "SYSTEM/OK"]
    thief_line = next(line for line in first_lines if "Mutant Thief" in line)
    assert "Year: 2000" in thief_line

    # Simulate travel updating canonical storage; ctx still holds stale state if any.
    canonical_store["players"][0]["pos"] = [2200, 0, 0]
    ctx["feedback_bus"] = DummyBus()
    ctx["player_state"] = {"players": [{"id": "player_thief", "pos": [1999, 0, 0]}]}

    class_menu.render_menu(ctx)
    refreshed_lines = [msg for channel, msg in ctx["feedback_bus"].messages if channel == "SYSTEM/OK"]
    thief_line = next(line for line in refreshed_lines if "Mutant Thief" in line)
    assert "Year: 2200" in thief_line


def test_class_menu_accepts_bury_all(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    called = {"bury_all": 0}

    def _fake_bury_all() -> None:
        called["bury_all"] += 1

    def _fake_load_state() -> dict[str, Any]:
        return player_state.ensure_class_profiles({"players": [], "active_id": None})

    monkeypatch.setattr(class_menu.player_reset, "bury_all", _fake_bury_all)
    monkeypatch.setattr(class_menu, "_load_canonical_state", _fake_load_state)

    class_menu.handle_input("bury all", ctx)

    assert called["bury_all"] == 1
    assert any(msg == ("SYSTEM/OK", "Player reset.") for msg in ctx["feedback_bus"].messages)
