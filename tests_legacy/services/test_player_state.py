from __future__ import annotations

import copy

from mutants.services import player_state


def _base_state() -> dict[str, object]:
    return {
        "active": {"class": "Thief", "pos": [2000, 0, 0]},
        "active_id": "p1",
        "bags": {"Thief": [], "Wizard": []},
        "inventory": [],
        "players": [
            {
                "id": "p1",
                "name": "Thief",
                "class": "Thief",
                "pos": [2000, 0, 0],
                "stats": {
                    "str": 2,
                    "int": 3,
                    "wis": 4,
                    "dex": 5,
                    "con": 6,
                    "cha": 7,
                },
                "hp": {"current": 8, "max": 9},
                "exhaustion": 1,
                "exp_points": 20,
                "level": 2,
                "ions": 10,
                "riblets": 3,
            },
            {
                "id": "p2",
                "name": "Wizard",
                "class": "Wizard",
                "pos": [2000, 0, 0],
                "stats": {
                    "str": 12,
                    "int": 13,
                    "wis": 14,
                    "dex": 15,
                    "con": 16,
                    "cha": 17,
                },
                "hp": {"current": 18, "max": 20},
                "exhaustion": 2,
                "exp_points": 40,
                "level": 4,
                "ions": 50,
                "riblets": 5,
            },
        ],
        "ions_by_class": {"Thief": 10, "Wizard": 50},
        "riblets_by_class": {"Thief": 3, "Wizard": 5},
        "exhaustion_by_class": {"Thief": 1, "Wizard": 2},
        "exp_by_class": {"Thief": 20, "Wizard": 40},
        "level_by_class": {"Thief": 2, "Wizard": 4},
        "hp_by_class": {
            "Thief": {"current": 8, "max": 9},
            "Wizard": {"current": 18, "max": 20},
        },
        "stats_by_class": {
            "Thief": {
                "str": 2,
                "int": 3,
                "wis": 4,
                "dex": 5,
                "con": 6,
                "cha": 7,
            },
            "Wizard": {
                "str": 12,
                "int": 13,
                "wis": 14,
                "dex": 15,
                "con": 16,
                "cha": 17,
            },
        },
    }


def test_normalize_clears_wield_missing_from_bag():
    base = _base_state()
    base["bags_by_class"] = {"Thief": [], "Wizard": []}
    base["wielded_by_class"] = {"Thief": "weapon-1"}
    base["wielded"] = "weapon-1"
    base["active"]["wielded"] = "weapon-1"

    normalized = player_state._normalize_player_state(copy.deepcopy(base))

    assert normalized["wielded_by_class"]["Thief"] is None
    assert normalized["active"]["wielded"] is None
    assert (
        normalized["active"].get("wielded_by_class", {}).get("Thief") is None
    )

    thief = next(player for player in normalized["players"] if player["class"] == "Thief")
    assert thief.get("wielded") is None
    assert thief.get("wielded_by_class", {}).get("Thief") is None


def test_normalize_clears_wield_matching_armour():
    base = _base_state()
    base["bags"]["Thief"] = ["arm-1", "weapon-2"]
    base["bags_by_class"] = {"Thief": ["arm-1", "weapon-2"], "Wizard": []}
    base["wielded_by_class"] = {"Thief": "arm-1"}
    base["wielded"] = "arm-1"
    base["active"]["wielded"] = "arm-1"
    base["equipment_by_class"] = {"Thief": {"armour": "arm-1"}}
    base["active"]["equipment_by_class"] = {"Thief": {"armour": "arm-1"}}
    base["players"][0]["equipment_by_class"] = {"Thief": {"armour": "arm-1"}}

    normalized = player_state._normalize_player_state(copy.deepcopy(base))

    assert normalized["wielded_by_class"]["Thief"] is None
    assert normalized["active"]["wielded"] is None
    assert (
        normalized["active"].get("wielded_by_class", {}).get("Thief") is None
    )

    thief = next(player for player in normalized["players"] if player["class"] == "Thief")
    assert thief.get("wielded") is None
    assert thief.get("wielded_by_class", {}).get("Thief") is None


def test_migrate_per_class_fields_populates_maps():
    state = {
        "active": {"class": "Thief", "pos": [2000, 0, 0]},
        "players": [
            {
                "id": "p1",
                "name": "Thief",
                "class": "Thief",
                "pos": [2000, 0, 0],
                "stats": {
                    "str": 2,
                    "int": 3,
                    "wis": 4,
                    "dex": 5,
                    "con": 6,
                    "cha": 7,
                },
                "hp": {"current": 8, "max": 9},
                "exhaustion": 1,
                "exp_points": 20,
                "level": 2,
                "ions": 10,
                "riblets": 3,
            },
            {
                "id": "p2",
                "name": "Wizard",
                "class": "Wizard",
                "pos": [2000, 0, 0],
                "stats": {
                    "str": 12,
                    "int": 13,
                    "wis": 14,
                    "dex": 15,
                    "con": 16,
                    "cha": 17,
                },
                "hp": {"current": 18, "max": 20},
                "exhaustion": 2,
                "exp_points": 40,
                "level": 4,
                "ions": 50,
                "riblets": 5,
            },
        ],
        "bags": {},
        "inventory": [],
    }

    migrated = player_state.migrate_per_class_fields(state)

    assert migrated["ions_by_class"] == {"Thief": 10, "Wizard": 50}
    assert migrated["riblets_by_class"] == {"Thief": 3, "Wizard": 5}
    assert migrated["exhaustion_by_class"] == {"Thief": 1, "Wizard": 2}
    assert migrated["exp_by_class"] == {"Thief": 20, "Wizard": 40}
    assert migrated["level_by_class"] == {"Thief": 2, "Wizard": 4}
    assert migrated["hp_by_class"]["Thief"] == {"current": 8, "max": 9}
    assert migrated["hp_by_class"]["Wizard"] == {"current": 18, "max": 20}
    assert migrated["stats_by_class"]["Wizard"]["int"] == 13
    assert migrated["ions"] == 10
    assert migrated["riblets"] == 3
    assert migrated["active"]["hp"] == {"current": 8, "max": 9}


def test_active_setters_affect_only_active_class(monkeypatch):
    base = _base_state()
    normalized = player_state._normalize_player_state(copy.deepcopy(base))

    saved: dict[str, object] = {}

    def fake_save(st):
        saved["state"] = copy.deepcopy(st)

    monkeypatch.setattr(player_state, "save_state", fake_save)

    player_state.set_ions_for_active(normalized, 123)
    normalized = copy.deepcopy(saved["state"])
    player_state.set_riblets_for_active(normalized, 77)
    normalized = copy.deepcopy(saved["state"])
    player_state.set_exhaustion_for_active(normalized, 5)
    normalized = copy.deepcopy(saved["state"])
    player_state.set_exp_for_active(normalized, 250)
    normalized = copy.deepcopy(saved["state"])
    player_state.set_level_for_active(normalized, 6)
    normalized = copy.deepcopy(saved["state"])
    player_state.set_hp_for_active(normalized, {"current": 31, "max": 40})
    normalized = copy.deepcopy(saved["state"])
    player_state.set_stats_for_active(
        normalized,
        {"str": 9, "int": 8, "wis": 7, "dex": 6, "con": 5, "cha": 4},
    )

    final_state = saved["state"]

    assert final_state["ions_by_class"]["Thief"] == 123
    assert final_state["ions_by_class"]["Wizard"] == 50
    assert final_state["riblets_by_class"]["Thief"] == 77
    assert final_state["riblets_by_class"]["Wizard"] == 5
    assert final_state["exhaustion_by_class"]["Thief"] == 5
    assert final_state["exhaustion_by_class"]["Wizard"] == 2
    assert final_state["exp_by_class"]["Thief"] == 250
    assert final_state["exp_by_class"]["Wizard"] == 40
    assert final_state["level_by_class"]["Thief"] == 6
    assert final_state["level_by_class"]["Wizard"] == 4
    assert final_state["hp_by_class"]["Thief"] == {"current": 31, "max": 40}
    assert final_state["hp_by_class"]["Wizard"] == {"current": 18, "max": 20}
    assert final_state["stats_by_class"]["Thief"] == {
        "str": 9,
        "int": 8,
        "wis": 7,
        "dex": 6,
        "con": 5,
        "cha": 4,
    }
    assert final_state["stats_by_class"]["Wizard"]["int"] == 13

    assert final_state["Ions"] == 123
    assert final_state["active"]["ions"] == 123
    assert final_state["riblets"] == 77
    assert final_state["active"]["riblets"] == 77
    assert final_state["exhaustion"] == 5
    assert final_state["active"]["exhaustion"] == 5
    assert final_state["exp_points"] == 250
    assert final_state["active"]["exp_points"] == 250
    assert final_state["level"] == 6
    assert final_state["active"]["level"] == 6
    assert final_state["hp"] == {"current": 31, "max": 40}
    assert final_state["active"]["hp"] == {"current": 31, "max": 40}
    assert final_state["stats"] == {
        "str": 9,
        "int": 8,
        "wis": 7,
        "dex": 6,
        "con": 5,
        "cha": 4,
    }

    assert player_state.get_ions_for_active(final_state) == 123
    assert player_state.get_riblets_for_active(final_state) == 77
    assert player_state.get_exhaustion_for_active(final_state) == 5
    assert player_state.get_exp_for_active(final_state) == 250
    assert player_state.get_level_for_active(final_state) == 6
    assert player_state.get_hp_for_active(final_state) == {"current": 31, "max": 40}
    assert player_state.get_stats_for_active(final_state)["str"] == 9


def test_evaluate_invariants_detects_missing_class_entry():
    state = player_state._normalize_player_state(copy.deepcopy(_base_state()))
    del state["ions_by_class"]["Thief"]

    assert player_state._evaluate_invariants(state) is False


def test_evaluate_invariants_detects_hp_relation_issue():
    state = player_state._normalize_player_state(copy.deepcopy(_base_state()))
    state["hp_by_class"]["Thief"]["current"] = 10
    state["hp_by_class"]["Thief"]["max"] = 5

    assert player_state._evaluate_invariants(state) is False
