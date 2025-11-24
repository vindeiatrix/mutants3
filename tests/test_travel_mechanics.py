from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mutants import state as state_mod
from mutants.commands import travel as travel_cmd
from mutants.registries import items_catalog as items_catalog_mod
from mutants.registries.sqlite_store import SQLiteConnectionManager
from mutants.services import player_state


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


class Runner:
    def __init__(self, ctx: Dict[str, Any]) -> None:
        self.ctx = ctx

    def __call__(self, raw: str) -> Dict[str, Any]:
        parts = raw.strip().split(maxsplit=1)
        if not parts:
            return self.ctx
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in {"travel", "tra"}:
            travel_cmd.travel_cmd(arg, self.ctx)
        else:  # pragma: no cover - defensive guard for future extensions
            raise ValueError(f"Unsupported command: {cmd}")
        return self.ctx


@pytest.fixture()
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
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

    items_catalog_mod._CATALOG_CACHE = None

    def _factory() -> Runner:
        ctx: Dict[str, Any] = {
            "feedback_bus": DummyBus(),
            "render_next": False,
            "world_loader": lambda year: SimpleNamespace(year=int(year)),
            "world_years": [2000, 2100, 2200, 2300],
        }
        ctx["player_state"] = player_state.load_state()
        player_state.ensure_player_state(ctx)
        return Runner(ctx)

    return _factory


def _seed_player_state(year: int, x: int, y: int, ions: int) -> None:
    base_state = {
        "players": [
            {
                "id": "player_thief",
                "class": "Thief",
                "pos": [year, x, y],
                "inventory": [],
                "ions": ions,
            }
        ],
        "active_id": "player_thief",
        "ions_by_class": {"Thief": ions},
        "pos": [year, x, y],
    }
    player_state.save_state(player_state.ensure_class_profiles(base_state))


def _get_player_ions(run: Runner) -> int:
    state = run.ctx.get("player_state") or player_state.load_state()
    return int(player_state.get_ions_for_active(state))


def _get_player_pos(run: Runner) -> tuple[int, int, int]:
    state = run.ctx.get("player_state") or player_state.load_state()
    return player_state.canonical_player_pos(state)


def _assert_message_contains(run: Runner, fragment: str) -> None:
    assert any(fragment in msg for _channel, msg in run.ctx["feedback_bus"].messages)


@pytest.mark.parametrize("year, ions", [(2000, 10000)])
def test_travel_standard_success(run: Any, year: int, ions: int) -> None:
    _seed_player_state(year, 5, 5, ions)
    runner = run()

    runner("travel 2100")

    assert _get_player_ions(runner) == ions - 3000
    assert _get_player_pos(runner) == (2100, 0, 0)
    _assert_message_contains(runner, "sent to the year 2100")


def test_travel_local_reset(run: Any) -> None:
    _seed_player_state(2000, 5, 5, 10000)
    runner = run()

    runner("travel 2000")

    assert _get_player_ions(runner) == 10000
    assert _get_player_pos(runner) == (2000, 0, 0)
    _assert_message_contains(runner, "already in the 21th Century")


def test_travel_insufficient_funds_abort(run: Any) -> None:
    _seed_player_state(2000, 5, 5, 100)
    runner = run()

    runner("travel 2100")

    assert _get_player_ions(runner) == 100
    assert _get_player_pos(runner) == (2000, 5, 5)
    _assert_message_contains(runner, "don't have enough ions")


def test_travel_catastrophic_failure(run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_player_state(2000, 5, 5, 4000)
    monkeypatch.setattr(travel_cmd.random, "choice", lambda seq: seq[1] if len(seq) > 1 else seq[0])
    runner = run()

    runner("travel 2200")

    assert _get_player_ions(runner) == 0
    year, x, y = _get_player_pos(runner)
    assert year in {2000, 2100}
    assert (x, y) == (0, 0)
    _assert_message_contains(runner, "gone terribly wrong")
