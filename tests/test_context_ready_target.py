from __future__ import annotations
from typing import Any, Dict

from mutants.app import context as context_mod
from mutants.services import player_state


class DummyWorld:
    def get_tile(self, _x: int, _y: int) -> Dict[str, Any]:
        return {"edges": {"N": {}, "S": {}, "E": {}, "W": {}}, "header_idx": 0}


def test_room_vm_keeps_ready_target_when_monsters_absent(monkeypatch):
    target_id = "Junkyard-Scrapper-123"
    state: Dict[str, Any] = {
        "active_id": "p1",
        "players": [
            {
                "id": "p1",
                "class": "Mutant Thief",
                "pos": [2400, 0, 0],
                "ready_target_by_class": {"Mutant Thief": target_id},
                "ready_target": target_id,
            }
        ],
        "ready_target_by_class": {"Mutant Thief": target_id},
        "ready_target": target_id,
        "pos": [2400, 0, 0],
    }

    runtime_ctx: Dict[str, Any] = {"player_state": state}
    monkeypatch.setattr(player_state, "_current_runtime_ctx", lambda: runtime_ctx)

    context_mod.build_room_vm(
        state,
        world_loader=lambda _year: DummyWorld(),
        headers=context_mod.ROOM_HEADERS,
        monsters=None,
        items=None,
    )

    assert player_state.get_ready_target_for_active(state) == target_id
    assert runtime_ctx["player_state"].get("ready_target") == target_id
