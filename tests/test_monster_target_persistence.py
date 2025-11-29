from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Iterable, MutableMapping, Sequence

import pytest
import sys
from pathlib import Path

SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mutants import state as state_mod
from mutants.commands import classmenu, travel as travel_cmd
from mutants.services import monster_ai, player_state as pstate
from mutants.services.monster_ai import tracking


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


class DummyMonsters:
    def __init__(self, records: Iterable[MutableMapping[str, Any]]) -> None:
        self.records = [record for record in records if isinstance(record, MutableMapping)]
        self.marked = False
        self.saved = False

    def list_all(self) -> Sequence[MutableMapping[str, Any]]:
        return list(self.records)

    def mark_dirty(self) -> None:
        self.marked = True

    def save(self) -> None:
        self.saved = True


@pytest.fixture()
def ctx_factory(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    monkeypatch.setattr(state_mod, "STATE_ROOT", tmp_path)

    def _builder() -> tuple[Dict[str, Any], DummyMonsters]:
        base_state: Dict[str, Any] = {
            "players": [
                {
                    "id": "player_thief",
                    "class": "Thief",
                    "pos": [2000, -3, 0],
                    "inventory": [],
                    "ions": 30000,
                }
            ],
            "active_id": "player_thief",
            "ions_by_class": {"Thief": 30000},
            "pos": [2000, -3, 0],
        }

        pstate.save_state(pstate.ensure_class_profiles(base_state))

        monster = {
            "id": "mon-1",
            "instance_id": "mon-1",
            "monster_id": "junkyard-scrapper",
            "pos": [2000, -3, 0],
            "hp": {"current": 1, "max": 1},
            "target_player_id": "player_thief",
            "_ai_state": {},
        }

        monsters = DummyMonsters([monster])

        ctx: Dict[str, Any] = {
            "feedback_bus": DummyBus(),
            "render_next": False,
            "world_loader": lambda year: SimpleNamespace(year=int(year)),
            "world_years": [2000, 2100],
            "monsters": monsters,
        }
        ctx["player_state"] = pstate.load_state()
        return ctx, monsters

    return _builder


def _monster(ctx_monsters: DummyMonsters) -> MutableMapping[str, Any]:
    monster = ctx_monsters.records[0]
    assert isinstance(monster, MutableMapping)
    return monster


def test_travel_keeps_aggro_and_tracks_positions(ctx_factory) -> None:
    ctx, monsters = ctx_factory()
    monster = _monster(monsters)

    tracking.record_target_position(monster, "player_thief", (2000, -3, 0))
    pstate.set_ready_target_for_active("mon-1")

    travel_cmd.travel_cmd("2100", ctx)
    monster_ai.on_player_command(ctx, token="travel", resolved="travel")

    pos_after, _ = tracking.get_target_position(monster, "player_thief")
    assert monster.get("target_player_id") == "player_thief"
    assert pos_after == (2100, 0, 0)

    travel_cmd.travel_cmd("2000", ctx)
    monster_ai.on_player_command(ctx, token="travel", resolved="travel")

    pos_return, _ = tracking.get_target_position(monster, "player_thief")
    assert monster.get("target_player_id") == "player_thief"
    assert pos_return == (2000, 0, 0)
    assert pstate.get_ready_target_for_active(pstate.load_state()) == "mon-1"


def test_class_menu_clears_player_and_monster_targets(ctx_factory) -> None:
    ctx, monsters = ctx_factory()
    monster = _monster(monsters)

    tracking.record_target_position(monster, "player_thief", (2000, -3, 0))
    pstate.set_ready_target_for_active("mon-1")

    classmenu.open_menu(ctx)

    assert pstate.get_ready_target_for_active(pstate.load_state()) is None
    assert monster.get("target_player_id") is None
    assert monsters.marked is True
    assert monsters.saved is True
