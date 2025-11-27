from __future__ import annotations

import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Callable

import pytest

SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mutants import state as state_mod
from mutants.commands.statistics import statistics_cmd
from mutants.registries.sqlite_store import SQLiteConnectionManager
from mutants.services import player_state


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


@pytest.fixture()
def ready_state_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, Callable[[Dict[str, Any] | None], Dict[str, Any]]]:
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    monkeypatch.setattr(state_mod, "STATE_ROOT", tmp_path)

    shutil.copytree(repo_root / "state", tmp_path, dirs_exist_ok=True)

    manager = SQLiteConnectionManager(tmp_path / "mutants.db")
    manager.connect()
    catalog_data = json.loads((repo_root / "state" / "items" / "catalog.json").read_text())
    for entry in catalog_data:
        manager.upsert_item_catalog(
            entry["item_id"], json.dumps(entry, ensure_ascii=False, sort_keys=True)
        )
    manager.close()

    target_id = "Rad-Swarm-Matron-844"
    base_payload: Dict[str, Any] = {
        "players": [
            {
                "id": "player_warrior",
                "class": "Mutant Warrior",
                "pos": [2000, 0, 0],
                "ready_target_by_class": {"Mutant Warrior": target_id},
                "ready_target": target_id,
                "inventory": [],
                "ions": 0,
            }
        ],
        "active_id": "player_warrior",
        "ions_by_class": {"Mutant Warrior": 0},
        "pos": [2000, 0, 0],
        "ready_target_by_class": {"Mutant Warrior": target_id},
        "ready_target": target_id,
    }

    def factory(monsters_state: Dict[str, Any] | None = None) -> Dict[str, Any]:
        ready_state = player_state.ensure_class_profiles(deepcopy(base_payload))
        player_state.save_state(ready_state)
        ctx: Dict[str, Any] = {
            "feedback_bus": DummyBus(),
            "render_next": False,
            "monsters": monsters_state,
            "player_state": player_state.load_state(),
        }
        monkeypatch.setattr(player_state, "_current_runtime_ctx", lambda: ctx)
        return ctx

    return target_id, factory


def test_statistics_retains_ready_target_when_separated(
    ready_state_factory: tuple[str, Callable[[Dict[str, Any] | None], Dict[str, Any]]]
) -> None:
    target_id, ctx_factory = ready_state_factory
    ctx = ctx_factory(monsters_state={})

    statistics_cmd("", ctx)

    assert any(
        msg == ("SYSTEM/OK", f"Ready to Combat: {target_id}") for msg in ctx["feedback_bus"].messages
    )
    assert player_state.get_ready_target_for_active(ctx["player_state"]) == target_id


def test_statistics_clears_ready_target_for_dead_monster(
    ready_state_factory: tuple[str, Callable[[Dict[str, Any] | None], Dict[str, Any]]]
) -> None:
    target_id, ctx_factory = ready_state_factory
    ctx = ctx_factory(
        monsters_state={target_id: {"hp": {"current": 0}, "name": "Fallen Hive"}}
    )

    statistics_cmd("", ctx)

    assert ("SYSTEM/OK", "Ready to Combat: NO ONE") in ctx["feedback_bus"].messages
