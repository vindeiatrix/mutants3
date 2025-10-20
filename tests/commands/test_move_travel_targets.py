from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.commands import move as move_cmd
from mutants.commands import travel as travel_cmd
from mutants.services import player_state as pstate


@dataclass
class _DummyDecision:
    passable: bool = True
    reason: str | None = None
    descriptor: str | None = None
    cur_raw: Mapping[str, Any] | None = None
    nbr_raw: Mapping[str, Any] | None = None
    reason_chain: Iterable[str] | None = None


class _DummyBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def push(self, kind: str, message: str, **_: Any) -> None:
        self.events.append((kind, message))


def _runtime_state_with_target(target: str) -> pstate.PlayerState:
    return pstate.PlayerState(
        {
            "active_id": "player-1",
            "players": [
                {
                    "id": "player-1",
                    "pos": [2000, 5, 7],
                }
            ],
        },
        combat_target_id=target,
    )


def test_move_keeps_runtime_combat_target(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_state = _runtime_state_with_target("monster-1")
    ctx: Dict[str, Any] = {
        "player_state": runtime_state,
        "world_loader": lambda year: {"year": year},
        "feedback_bus": _DummyBus(),
        "room_entry_event": None,
        "render_next": False,
    }

    monkeypatch.setattr(move_cmd.ER, "resolve", lambda *_, **__: _DummyDecision())

    persisted_positions: Dict[str, Any] = {}

    def _fake_mutate_active(mutator):
        state = {
            "active_id": "player-1",
            "players": [
                {
                    "id": "player-1",
                    "pos": [2000, 5, 7],
                }
            ],
        }
        active = state["players"][0]
        mutator(state, active)
        persisted_positions.update(active)
        return state

    monkeypatch.setattr(move_cmd.pstate, "mutate_active", _fake_mutate_active)

    move_cmd.move("N", ctx)

    assert runtime_state.combat_target_id == "monster-1"
    assert ctx["player_state"].combat_target_id == "monster-1"
    assert persisted_positions["pos"] == [2000, 5, 8]


def test_travel_runtime_state_preserves_target() -> None:
    runtime_state = _runtime_state_with_target("monster-7")
    ctx: Dict[str, Any] = {"player_state": runtime_state}

    new_state = {"active_id": "player-1", "players": []}
    travel_cmd._set_runtime_state(ctx, new_state)

    updated_state = ctx["player_state"]
    assert isinstance(updated_state, pstate.PlayerState)
    assert updated_state is not runtime_state
    assert updated_state.combat_target_id == "monster-7"
