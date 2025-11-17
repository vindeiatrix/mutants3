from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mutants import state as state_mod
from mutants.commands import classmenu as classmenu_cmd
from mutants.commands import combat as combat_cmd
from mutants.commands import move as move_cmd
from mutants.commands import travel as travel_cmd
from mutants.services import player_state
from mutants.ui import class_menu


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


class _PassableDecision(SimpleNamespace):
    pass


class _FakeWorld:
    def __init__(self, year: int) -> None:
        self.year = year

    def get_tile(self, _x: int, _y: int) -> dict:
        return {"edges": {"N": {}, "S": {}, "E": {}, "W": {}}, "header_idx": 0}


class _FakeMonsters:
    def __init__(self, positions: list[tuple[int, int, int]]) -> None:
        self._positions = positions

    def list_at(self, year: int, x: int, y: int) -> list[dict]:
        entries = []
        for idx, pos in enumerate(self._positions):
            if pos == (year, x, y):
                entries.append(
                    {
                        "id": f"monster-{idx}",
                        "monster_id": "shadow",  # matches query prefix
                        "name": "Shadow Monster",
                        "hp": {"current": 5},
                    }
                )
        return entries


def _initial_state() -> dict:
    return {
        "players": [
            {
                "id": "player_thief",
                "class": "Thief",
                "pos": [2000, 0, 0],
                "inventory": [],
                "level": 1,
                "ions": 15000,
            }
        ],
        "active_id": "player_thief",
        "ions_by_class": {"Thief": 15000},
    }


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(state_mod, "STATE_ROOT", tmp_path)
    return tmp_path


def test_travel_and_menu_reflect_canonical_positions(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    player_state.save_state(player_state.ensure_class_profiles(_initial_state()))

    monkeypatch.setattr(
        move_cmd.ER,
        "resolve",
        lambda world, dyn_mod, year, x, y, dir_code, actor=None: _PassableDecision(
            passable=True,
            descriptor="open",
            reason=None,
            reason_chain=[],
            cur_raw={},
            nbr_raw={},
        ),
    )

    ctx = {
        "feedback_bus": DummyBus(),
        "player_state": player_state.load_state(),
        "render_next": False,
        "world_loader": lambda year: _FakeWorld(year),
        "world_years": [2000, 2100, 2200, 2300],
    }

    player_state.ensure_player_state(ctx)
    travel_cmd.travel_cmd("2300", ctx)
    move_cmd.move("E", ctx)
    move_cmd.move("N", ctx)

    monsters = _FakeMonsters([(2300, 1, 1)])
    ctx["monsters"] = monsters
    combat_result = combat_cmd.combat_cmd("shadow", ctx)
    assert combat_result["ok"] is True

    canonical = player_state.load_state()
    assert player_state.canonical_player_pos(canonical) == (2300, 1, 1)
    thief_entry = next(p for p in canonical["players"] if p.get("class") == "Thief")
    assert thief_entry["pos"] == [2300, 1, 1]

    player_file = state_root / "playerlivestate.json"
    persisted = json.loads(player_file.read_text(encoding="utf-8"))
    assert "active" not in persisted

    menu_ctx: dict = {"feedback_bus": DummyBus(), "mode": "class_select", "render_next": False}
    classmenu_cmd.open_menu(menu_ctx)

    menu_lines = [msg for channel, msg in menu_ctx["feedback_bus"].messages if channel == "SYSTEM/OK"]
    thief_line = next(line for line in menu_lines if "Mutant Thief" in line)
    assert "Year: 2300" in thief_line
    assert "( 1  1)" in thief_line

    handle_ctx = {"feedback_bus": DummyBus(), "mode": "class_select", "render_next": False}
    class_menu.handle_input("1", handle_ctx)
    reentered = handle_ctx["player_state"]
    assert player_state.canonical_player_pos(reentered) == (2300, 1, 1)
    assert handle_ctx["session"]["active_class"] == "Thief"
    assert handle_ctx["render_next"] is True
