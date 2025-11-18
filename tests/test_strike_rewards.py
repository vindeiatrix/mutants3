from __future__ import annotations

import sys
import types

sys.path.append("src")

import mutants.commands.strike as strike
from mutants.services import player_state as pstate


def test_kill_rewards_stay_with_active_class(monkeypatch):
    # Prevent item minting side effects while exercising reward logic.
    def _fail_drop(**_: object):
        raise RuntimeError("no drops in test")

    monkeypatch.setattr(strike.combat_loot, "drop_monster_loot", _fail_drop)
    monkeypatch.setattr(strike, "load_monsters_catalog", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(pstate, "save_state", lambda data: None)

    state = {
        "class": "Wizard",
        "active_id": "player_wizard",
        "players": [
            {"id": "player_wizard", "class": "Wizard", "ions": 10, "riblets": 1, "exp_points": 0},
            {"id": "player_thief", "class": "Thief", "ions": 99, "riblets": 2, "exp_points": 0},
        ],
        "ions_by_class": {"Wizard": 10, "Thief": 99},
        "riblets_by_class": {"Wizard": 1, "Thief": 2},
        "exp_by_class": {"Wizard": 0, "Thief": 0},
    }

    monster = {"ions": 7, "riblets": 3, "monster_id": "junkyard_scrapper", "level": 1}

    summary: dict[str, object] = {}
    strike._award_player_progress(
        monster_payload=monster,
        state=state,
        item_catalog={},
        summary=summary,
        bus=types.SimpleNamespace(push=lambda *args, **kwargs: None),
    )

    assert state["ions_by_class"]["Wizard"] == 17
    assert state["ions_by_class"]["Thief"] == 99
    assert state["riblets_by_class"]["Wizard"] == 4
    assert state["riblets_by_class"]["Thief"] == 2
    # Exp bonus should be pulled from the catalog JSON fallback when the DB store is unavailable.
    assert state["exp_by_class"]["Wizard"] == 105
    assert state["exp_by_class"]["Thief"] == 0
    assert summary["drops_minted"] == []
    assert summary["drops_vaporized"] == []
