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
    monkeypatch.setattr(strike, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))

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


def test_kill_rewards_use_riblet_range(monkeypatch):
    monkeypatch.setattr(strike.pstate, "save_state", lambda data: None)
    monkeypatch.setattr(strike, "monster_exp_for", lambda level, bonus: 0)
    monkeypatch.setattr(strike, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))

    state = {
        "class": "Wizard",
        "active_id": "player_wizard",
        "players": [
            {"id": "player_wizard", "class": "Wizard", "ions": 0, "riblets": 0, "exp_points": 0}
        ],
        "ions_by_class": {"Wizard": 0},
        "riblets_by_class": {"Wizard": 0},
        "exp_by_class": {"Wizard": 0},
    }

    monster = {
        "monster_id": "junkyard_scrapper",
        "level": 1,
        "ions": 0,
        "riblets_min": 1,
        "riblets_max": 4,
    }

    strike._award_player_progress(
        monster_payload=monster,
        state=state,
        item_catalog={},
        summary={},
        bus=types.SimpleNamespace(push=lambda *args, **kwargs: None),
    )

    assert state["riblets_by_class"]["Wizard"] == 4
    assert state["ions_by_class"]["Wizard"] == 0


def test_strike_uses_initialized_state(monkeypatch):
    # Ensure player state is injected into the context before reward resolution.
    monkeypatch.setattr(strike.pstate, "save_state", lambda data: None)
    monkeypatch.setattr(strike.pstate, "get_ready_target_for_active", lambda state: "m1")
    monkeypatch.setattr(strike.pstate, "clear_ready_target_for_active", lambda **kwargs: None)
    monkeypatch.setattr(strike, "resolve_ready_target_in_tile", lambda ctx: "m1")
    monkeypatch.setattr(strike.pstate, "get_wielded_weapon_id", lambda state: None)
    monkeypatch.setattr(strike.pstate, "canonical_player_pos", lambda state: (0, 0, 0))
    monkeypatch.setattr(strike.items_catalog, "load_catalog", lambda: {})
    monkeypatch.setattr(strike.items_wear, "build_wear_event", lambda **_: {})
    monkeypatch.setattr(strike.items_wear, "wear_from_event", lambda event: 0)
    monkeypatch.setattr(strike, "_apply_weapon_wear", lambda *args, **kwargs: None)
    monkeypatch.setattr(strike, "_apply_armour_wear", lambda *args, **kwargs: None)
    monkeypatch.setattr(strike, "load_monsters_catalog", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(strike, "monster_exp_for", lambda level, bonus: 50)
    monkeypatch.setattr(strike, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))

    state = {
        "active_id": "player_wizard",
        "class": "Wizard",
        "players": [
            {
                "id": "player_wizard",
                "class": "Wizard",
                "ions": 0,
                "riblets": 0,
                "exp_points": 0,
            }
        ],
        "ions_by_class": {"Wizard": 0},
        "riblets_by_class": {"Wizard": 0},
        "exp_by_class": {"Wizard": 0},
        "active": {"id": "player_wizard", "class": "Wizard", "ions": 0, "riblets": 0, "exp_points": 0},
    }

    monster = {
        "id": "m1",
        "monster_id": "junkyard_scrapper",
        "hp": {"current": 1, "max": 1},
        "armour_class": 0,
        "level": 1,
        "ions": 2,
        "riblets": 3,
        "pos": (0, 0, 0),
    }

    class DummyMonsters:
        def get(self, monster_id):
            return monster if monster_id == "m1" else None

        def kill_monster(self, monster_id):
            assert monster_id == "m1"
            return {"monster": monster, "drops": [], "pos": monster.get("pos")}

    monkeypatch.setattr(strike, "_load_monsters", lambda ctx: DummyMonsters())
    monkeypatch.setattr(
        strike.damage_engine,
        "resolve_attack",
        lambda item, active, target: types.SimpleNamespace(damage=1, source="melee"),
    )

    ctx = {"feedback_bus": types.SimpleNamespace(push=lambda *args, **kwargs: None)}

    def _ensure_player_state(context):
        context["player_state"] = state
        return state["active"]

    monkeypatch.setattr(strike, "ensure_player_state", _ensure_player_state)

    result = strike.strike_cmd("m1", ctx)

    assert result["killed"] is True
    assert state["ions_by_class"]["Wizard"] == 2
    assert state["riblets_by_class"]["Wizard"] == 3
    assert state["exp_by_class"]["Wizard"] == 50
