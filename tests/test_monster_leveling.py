from __future__ import annotations

from pathlib import Path

from mutants.services import monster_leveling, monsters_state
from mutants.ui.feedback import FeedbackBus


def _build_state(tmp_path: Path) -> monsters_state.MonstersState:
    raw = [
        {
            "id": "ogre#1",
            "level": 1,
            "stats": {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            "hp": {"current": 5, "max": 5},
        }
    ]
    normalized = monsters_state.normalize_records(raw, catalog={})
    return monsters_state.MonstersState(tmp_path / "instances.json", normalized)


def test_monster_levels_on_kill(tmp_path: Path, monsters_store) -> None:
    state = _build_state(tmp_path)
    monster = state.get("ogre#1")
    assert monster is not None

    initial_weapon_damage = monster["derived"]["weapon_damage"]

    bus = FeedbackBus()
    monster_leveling.attach(bus, state)

    bus.push("COMBAT/KILL", "ogre crushes foe", killer_id="ogre#1", victim_id="hero#1")

    assert monster["level"] == 2
    for stat in ("str", "dex", "con", "int", "wis", "cha"):
        assert monster["stats"][stat] == 20

    assert monster["hp"] == {"current": 15, "max": 15}

    derived = monster["derived"]
    assert derived["weapon_damage"] == initial_weapon_damage + 1
    assert derived["dex_bonus"] == 2
    assert derived["armour_class"] == 2


def test_ignores_non_monster_kills(tmp_path: Path, monsters_store) -> None:
    state = _build_state(tmp_path)
    monster = state.get("ogre#1")
    assert monster is not None

    bus = FeedbackBus()
    monster_leveling.attach(bus, state)

    bus.push("COMBAT/KILL", "player victory", killer_id="player#1", victim_id="ogre#1")

    assert monster["level"] == 1
