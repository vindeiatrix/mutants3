from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mutants import state as state_mod
from mutants.commands import move
from mutants.registries.sqlite_store import SQLiteConnectionManager
from mutants.services import player_state


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


class OpenWorld:
    def get_tile(self, year: int, x: int, y: int) -> Dict[str, Any]:  # pragma: no cover - minimal stub
        return {
            "edges": {
                "N": {"base": "open"},
                "S": {"base": "open"},
                "E": {"base": "open"},
                "W": {"base": "open"},
            }
        }


@pytest.fixture()
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    monkeypatch.setattr(state_mod, "STATE_ROOT", tmp_path)

    shutil.copytree(repo_root / "state", tmp_path, dirs_exist_ok=True)

    manager = SQLiteConnectionManager(tmp_path / "mutants.db")
    manager.connect()
    catalog_data = json.loads((repo_root / "state" / "items" / "catalog.json").read_text())
    for entry in catalog_data:
        manager.upsert_item_catalog(entry["item_id"], json.dumps(entry, ensure_ascii=False, sort_keys=True))
    manager.close()

    target_id = "Rad-Swarm-Matron-844"
    base_state = player_state.ensure_class_profiles(
        {
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
    )
    player_state.save_state(base_state)

    return {
        "feedback_bus": DummyBus(),
        "render_next": False,
        "world_loader": lambda year: OpenWorld(),
        "world_years": [2000],
        "player_state": player_state.load_state(),
    }


def test_move_keeps_ready_target(ctx: Dict[str, Any]) -> None:
    move.move("E", ctx)

    assert player_state.get_ready_target_for_active(ctx["player_state"]) == "Rad-Swarm-Matron-844"
