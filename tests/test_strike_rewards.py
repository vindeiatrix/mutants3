from __future__ import annotations

import sys
import types

sys.path.append("src")

from mutants.services import combat_actions
from mutants.services import player_state as pstate


def test_kill_rewards_stay_with_active_class(monkeypatch):
    # Prevent item minting side effects while exercising reward logic.
    def _fail_drop(**_: object):
        raise RuntimeError("no drops in test")

    monkeypatch.setattr(combat_actions.combat_loot, "drop_monster_loot", _fail_drop)
    monkeypatch.setattr(combat_actions, "load_monsters_catalog", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(pstate, "save_state", lambda data: None)
    monkeypatch.setattr(combat_actions, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))

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

    monster = {
        "ions": 7,
        "monster_id": "junkyard_scrapper",
        "level": 1,
    }

    summary: dict[str, object] = {}
    combat_actions._award_player_progress(
        monster_payload=monster,
        state=state,
        item_catalog={},
        summary=summary,
        bus=types.SimpleNamespace(push=lambda *args, **kwargs: None),
    )

    assert state["ions_by_class"]["Wizard"] == 17
    assert state["ions_by_class"]["Thief"] == 99
    assert state["riblets_by_class"]["Wizard"] == 3
    assert state["riblets_by_class"]["Thief"] == 2
    # Exp bonus should be pulled from the catalog JSON fallback when the DB store is unavailable.
    assert state["exp_by_class"]["Wizard"] == 5
    assert state["exp_by_class"]["Thief"] == 0
    assert summary["drops_minted"] == []
    assert summary["drops_vaporized"] == []


def test_catalog_overrides_payload_rewards(monkeypatch):
    def _fail_drop(**_: object):
        raise RuntimeError("no drops in test")

    catalog = {"junkyard_scrapper": {"exp_bonus": 5, "riblets_min": 0, "riblets_max": 2}}

    monkeypatch.setattr(combat_actions.combat_loot, "drop_monster_loot", _fail_drop)
    monkeypatch.setattr(combat_actions, "load_monsters_catalog", lambda: catalog)
    monkeypatch.setattr(combat_actions, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))
    monkeypatch.setattr(pstate, "save_state", lambda data: None)

    state = {
        "class": "Wizard",
        "active_id": "player_wizard",
        "players": [
            {"id": "player_wizard", "class": "Wizard", "ions": 0, "riblets": 0, "exp_points": 0},
        ],
        "ions_by_class": {"Wizard": 0},
        "riblets_by_class": {"Wizard": 0},
        "exp_by_class": {"Wizard": 0},
    }

    monster = {
        "monster_id": "junkyard_scrapper",
        "exp_bonus": 999,
        "riblets_min": 7,
        "riblets_max": 9,
    }

    combat_actions._award_player_progress(
        monster_payload=monster,
        state=state,
        item_catalog={},
        summary={},
        bus=types.SimpleNamespace(push=lambda *args, **kwargs: None),
    )

    # Catalog values should override the payload-provided values.
    assert state["exp_by_class"]["Wizard"] == 5
    assert state["riblets_by_class"]["Wizard"] == 2


def test_kill_rewards_use_riblet_range(monkeypatch):
    monkeypatch.setattr(combat_actions.pstate, "save_state", lambda data: None)
    monkeypatch.setattr(combat_actions, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))

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
        "monster_id": "custom_test_monster",
        "level": 1,
        "ions": 0,
        "riblets_min": 1,
        "riblets_max": 4,
    }

    combat_actions._award_player_progress(
        monster_payload=monster,
        state=state,
        item_catalog={},
        summary={},
        bus=types.SimpleNamespace(push=lambda *args, **kwargs: None),
    )

    # When the monster is not present in the catalog, fall back to the payload range.
    assert state["riblets_by_class"]["Wizard"] == 4
    assert state["ions_by_class"]["Wizard"] == 0


def test_strike_uses_initialized_state(monkeypatch):
    # Ensure player state is injected into the context before reward resolution.
    monkeypatch.setattr(combat_actions.pstate, "save_state", lambda data: None)
    monkeypatch.setattr(combat_actions.pstate, "get_ready_target_for_active", lambda state: "m1")
    monkeypatch.setattr(combat_actions.pstate, "clear_ready_target_for_active", lambda **kwargs: None)
    monkeypatch.setattr(combat_actions, "resolve_ready_target_in_tile", lambda ctx: "m1")
    monkeypatch.setattr(combat_actions.pstate, "get_wielded_weapon_id", lambda state: None)
    monkeypatch.setattr(combat_actions.pstate, "canonical_player_pos", lambda state: (0, 0, 0))
    monkeypatch.setattr(combat_actions.items_catalog, "load_catalog", lambda: {})
    monkeypatch.setattr(combat_actions.items_wear, "build_wear_event", lambda **_: {})
    monkeypatch.setattr(combat_actions.items_wear, "wear_from_event", lambda event: 0)
    monkeypatch.setattr(combat_actions, "_apply_weapon_wear", lambda *args, **kwargs: None)
    monkeypatch.setattr(combat_actions, "_apply_armour_wear", lambda *args, **kwargs: None)
    monkeypatch.setattr(combat_actions, "load_monsters_catalog", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(combat_actions, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))

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

    monkeypatch.setattr(combat_actions, "_load_monsters", lambda ctx: DummyMonsters())
    monkeypatch.setattr(
        combat_actions.damage_engine,
        "resolve_attack",
        lambda item, active, target: types.SimpleNamespace(damage=1, source="melee"),
    )

    ctx = {"feedback_bus": types.SimpleNamespace(push=lambda *args, **kwargs: None)}

    def _ensure_player_state(context):
        context["player_state"] = state
        return state["active"]

    monkeypatch.setattr(combat_actions, "ensure_player_state", _ensure_player_state)

    result = combat_actions.perform_melee_attack(ctx)

    assert result["killed"] is True
    assert state["ions_by_class"]["Wizard"] == 2
    assert state["riblets_by_class"]["Wizard"] == 2
    assert state["exp_by_class"]["Wizard"] == 5


def test_kill_block_announces_rewards_and_drops(monkeypatch):
    monkeypatch.setattr(combat_actions.pstate, "save_state", lambda data: None)
    monkeypatch.setattr(combat_actions.pstate, "get_ready_target_for_active", lambda state: "m1")
    monkeypatch.setattr(combat_actions.pstate, "clear_ready_target_for_active", lambda **kwargs: None)
    monkeypatch.setattr(combat_actions.pstate, "canonical_player_pos", lambda state: (0, 0, 0))
    monkeypatch.setattr(combat_actions, "resolve_ready_target_in_tile", lambda ctx: "m1")
    monkeypatch.setattr(combat_actions, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))

    catalog = {
        "hell_blade": {"name": "Hell-Blade"},
        "skull": {"name": "Skull"},
        "demon_cloth": {"name": "Demon-Cloth"},
    }
    monkeypatch.setattr(combat_actions.items_catalog, "load_catalog", lambda: catalog)
    monkeypatch.setattr(
        combat_actions,
        "load_monsters_catalog",
        lambda: {"junkyard_scrapper": {"exp_bonus": 5, "riblets_min": 2, "riblets_max": 2}},
    )

    minted = [
        {"item_id": "hell_blade", "drop_source": "bag", "iid": "bag1"},
        {"item_id": "demon_cloth", "drop_source": "armour", "iid": "arm1"},
        {"item_id": "skull", "drop_source": "skull", "iid": "skull1"},
    ]
    monkeypatch.setattr(
        combat_actions.combat_loot,
        "drop_monster_loot",
        lambda **_: (list(minted), []),
    )

    state = {
        "active_id": "player_wizard",
        "class": "Wizard",
        "players": [
            {"id": "player_wizard", "class": "Wizard", "ions": 0, "riblets": 0, "exp_points": 0}
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
        "riblets_min": 2,
        "riblets_max": 2,
        "pos": (0, 0, 0),
    }

    class DummyMonsters:
        def get(self, monster_id):
            return monster if monster_id == "m1" else None

        def kill_monster(self, monster_id):
            assert monster_id == "m1"
            return {"monster": monster, "drops": [], "pos": monster.get("pos")}

    monkeypatch.setattr(combat_actions, "_load_monsters", lambda ctx: DummyMonsters())
    monkeypatch.setattr(
        combat_actions.damage_engine,
        "resolve_attack",
        lambda item, active, target: types.SimpleNamespace(damage=1, source="melee"),
    )

    events: list[tuple[str, str]] = []

    class DummyBus:
        def push(self, kind, text, **_: object):
            events.append((kind, text))

    ctx = {"feedback_bus": DummyBus()}

    def _ensure_player_state(context):
        context["player_state"] = state
        return state["active"]

    monkeypatch.setattr(combat_actions, "ensure_player_state", _ensure_player_state)

    result = combat_actions.perform_melee_attack(ctx)

    assert result["killed"] is True

    kill_texts = [text for kind, text in events if kind in {"COMBAT/KILL", "COMBAT/INFO"}]
    assert kill_texts == [
        "You have slain junkyard_scrapper!",
        "Your experience points are increased by 5!",
        "You collect 2 Riblets and 2 ions from the slain body.",
        "A Hell-Blade is falling from junkyard_scrapper's body!",
        "A Skull is falling from junkyard_scrapper's body!",
        "A Demon-Cloth is falling from junkyard_scrapper's body!",
        "junkyard_scrapper is crumbling to dust!",
    ]


def test_armour_drop_is_last_even_when_bag_entries_missing(monkeypatch):
    monkeypatch.setattr(combat_actions.pstate, "save_state", lambda data: None)
    monkeypatch.setattr(combat_actions, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))
    monkeypatch.setattr(combat_actions, "load_monsters_catalog", lambda: (_ for _ in ()).throw(FileNotFoundError()))

    order: list[str] = []

    def _capture_drop_order(*, bag_entries=None, armour_entry=None, **_: object):
        for entry in bag_entries or []:
            order.append(str(entry.get("item_id")))
        order.append("skull")
        if armour_entry:
            order.append(str(armour_entry.get("item_id")))
        return ([], [])

    monkeypatch.setattr(combat_actions.combat_loot, "drop_monster_loot", _capture_drop_order)

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
        "hp": {"current": 1, "max": 1},
        "armour_slot": {"item_id": "torn_overalls", "iid": "armour1"},
        "bag": [
            {"item_id": "rusty_shiv", "iid": "bag1"},
            {"item_id": "bolt_pouch", "iid": "bag2"},
        ],
    }

    summary = {
        "monster": monster,
        "drops": [
            {"item_id": "rusty_shiv", "iid": "bag1"},
            {"item_id": "bolt_pouch", "iid": "bag2"},
            {"item_id": "torn_overalls", "iid": "armour1"},
        ],
        "pos": (0, 0, 0),
    }

    combat_actions._award_player_progress(
        monster_payload=monster,
        state=state,
        item_catalog={},
        summary=summary,
        bus=types.SimpleNamespace(push=lambda *args, **kwargs: None),
    )

    assert order == ["rusty_shiv", "bolt_pouch", "skull", "torn_overalls"]


def test_armour_in_bag_isnt_delayed(monkeypatch):
    monkeypatch.setattr(combat_actions.pstate, "save_state", lambda data: None)
    monkeypatch.setattr(combat_actions, "_RNG", types.SimpleNamespace(randint=lambda mn, mx: mx))

    monster = {
        "monster_id": "junkyard_scrapper",
        "hp": {"current": 1, "max": 1},
        "armour_slot": {"item_id": "scrap_armour", "iid": "armour1"},
        "bag": [{"item_id": "torn_overalls", "iid": "bag1", "armour_class": 1}],
    }

    minted = [
        {"item_id": "torn_overalls", "drop_source": "bag", "iid": "bag1", "armour_class": 1},
        {"item_id": "skull", "drop_source": "skull", "iid": "skull1"},
        {"item_id": "scrap_armour", "drop_source": "armour", "iid": "armour1", "armour_class": 2},
    ]

    ordered = combat_actions._sorted_drop_messages(minted, monster.get("armour_slot"))

    assert [entry.get("item_id") for entry in ordered] == [
        "torn_overalls",
        "skull",
        "scrap_armour",
    ]
