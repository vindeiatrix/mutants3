from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Tuple

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.debug import turnlog
from mutants.registries import items_instances as itemsreg
from mutants.services import audio_cues, monsters_state
from mutants.services.combat_config import CombatConfig
from mutants.services.monster_ai import pursuit
from mutants.services.monster_ai.pursuit import attempt_pursuit


class FixedRNG:
    def __init__(self, value: int) -> None:
        self.value = int(value)

    def randrange(self, upper: int) -> int:  # pragma: no cover - signature parity
        return int(self.value)


class DummyWorld:
    def __init__(self) -> None:  # pragma: no cover - trivial container
        self.tiles: Dict[Tuple[int, int], Dict[str, Any]] = {}


@pytest.fixture(autouse=True)
def _suppress_turnlog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turnlog, "emit", lambda ctx, kind, **meta: None)


@pytest.fixture(autouse=True)
def _disable_monster_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monsters_state, "_refresh_monster_derived", lambda monster: None)


@pytest.fixture(autouse=True)
def _clear_ground_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(itemsreg, "list_instances_at", lambda year, x, y: [])


@pytest.fixture(autouse=True)
def _passable_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pursuit.edge_resolver,
        "resolve",
        lambda *args, **kwargs: SimpleNamespace(passable=True, reason="open"),
    )


@pytest.fixture(autouse=True)
def _simple_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_path(
        year: int,
        start: Tuple[int, int],
        target: Tuple[int, int],
        *,
        world: Any | None = None,
        dynamics: Any | None = None,
    ) -> Iterable[Tuple[int, int]]:
        if start == target:
            return [start]
        step_x = start[0] + (1 if target[0] > start[0] else -1 if target[0] < start[0] else 0)
        step_y = start[1] + (1 if target[1] > start[1] else -1 if target[1] < start[1] else 0)
        return [start, (step_x, step_y), target]

    monkeypatch.setattr(pursuit.world_years, "find_path_between", fake_path)


def test_attempt_pursuit_emits_footsteps_audio_when_adjacent_player(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx: Dict[str, Any] = {
        "monster_ai_world_loader": lambda year: DummyWorld(),
    }

    monster: Dict[str, Any] = {
        "id": "m-1",
        "pos": [2000, 0, 0],
        "bag": [],
        "hp": {"current": 50, "max": 50},
        "ions": 20,
        "ions_max": 100,
    }

    rng = FixedRNG(0)

    result = attempt_pursuit(monster, (2000, 1, 0), rng, ctx=ctx, config=CombatConfig())

    assert result is True
    assert monster["pos"] == [2000, 1, 0]

    cues = audio_cues.drain(ctx)
    assert cues == ["You hear footsteps right next to you to the west."]
