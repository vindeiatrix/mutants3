from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, Mapping, MutableMapping

import pytest

from mutants.services import monster_actions


class _DummyBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def push(self, kind: str, text: str, **_: Any) -> None:
        self.events.append((kind, text))


class _FixedRng:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = list(values)
        if not self._values:
            self._values = [0.0]
        self._idx = 0

    def random(self) -> float:
        value = self._values[min(self._idx, len(self._values) - 1)]
        self._idx += 1
        return value


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monster_actions, "_mark_monsters_dirty", lambda ctx: ctx.setdefault("_dirty", True))


def _force_action(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(monster_actions, "_select_action", lambda m, c, r: name)


def test_attack_uses_innate_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {"id": "ogre#1", "hp": {"current": 10, "max": 10}, "wielded": None}
    bus = _DummyBus()
    ctx: Dict[str, Any] = {"feedback_bus": bus}

    state = {"hp_by_class": {"fighter": {"current": 30, "max": 30}}, "active_id": "player"}
    active = {"hp": {"current": 30, "max": 30}, "stats": {"dex": 10}}

    monkeypatch.setattr(monster_actions.pstate, "get_active_pair", lambda hint=None: (state, active))

    recorded: Dict[str, int] = {}

    def _fake_set_hp(st: Mapping[str, Any], hp: Mapping[str, Any]) -> Mapping[str, Any]:
        recorded.update(hp)  # type: ignore[arg-type]
        return dict(hp)

    monkeypatch.setattr(monster_actions.pstate, "set_hp_for_active", _fake_set_hp)
    monkeypatch.setattr(monster_actions.damage_engine, "compute_base_damage", lambda *args, **kwargs: -5)
    monkeypatch.setattr(monster_actions.items_wear, "wear_from_event", lambda payload: 0)
    monkeypatch.setattr(monster_actions, "_apply_weapon_wear", lambda *args, **kwargs: None)

    _force_action(monkeypatch, "attack")

    monster_actions.execute_random_action(monster, ctx, rng=_FixedRng([0.0]))

    assert recorded["current"] == 24 and recorded["max"] == 30
    assert any("6 damage" in text for _, text in bus.events)


def test_pickup_prefers_stronger_item(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {"id": "ghoul#1", "hp": {"current": 10, "max": 10}, "pos": [2000, 1, 2], "bag": []}
    bus = _DummyBus()
    ctx: Dict[str, Any] = {"feedback_bus": bus}

    ground_items = [
        {"iid": "weak", "item_id": "club", "enchant_level": 0, "condition": 100},
        {"iid": "strong", "item_id": "blade", "enchant_level": 0, "condition": 100},
    ]

    monkeypatch.setattr(monster_actions.itemsreg, "list_instances_at", lambda *_: ground_items)
    monkeypatch.setattr(monster_actions.itemsreg, "clear_position_at", lambda iid, *args: iid == "strong")
    monkeypatch.setattr(monster_actions.itemsreg, "get_instance", lambda iid: next((inst for inst in ground_items if inst["iid"] == iid), None))
    monkeypatch.setattr(monster_actions, "_load_catalog", lambda: {"club": {"base_power": 3}, "blade": {"base_power": 9}})

    _force_action(monkeypatch, "pickup")

    monster_actions.execute_random_action(monster, ctx, rng=_FixedRng([0.0]))

    bag = monster.get("bag") or []
    assert any(entry.get("iid") == "strong" for entry in bag)
    assert "strong" in monster_actions._picked_up_iids(monster)


def test_convert_only_uses_picked_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "lich#1",
        "hp": {"current": 8, "max": 8},
        "bag": [
            {"iid": "native", "item_id": "dagger", "enchant_level": 0},
            {"iid": "pickup", "item_id": "wand", "enchant_level": 0},
        ],
        "ions": 0,
    }
    monster_actions._add_picked_up(monster, "pickup")

    bus = _DummyBus()
    ctx: Dict[str, Any] = {"feedback_bus": bus}

    monkeypatch.setattr(monster_actions, "_load_catalog", lambda: {"wand": {"convert_ions": 1200}})
    monkeypatch.setattr(monster_actions.itemsreg, "delete_instance", lambda iid: iid == "pickup")
    monkeypatch.setattr(monster_actions.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": "wand"})

    _force_action(monkeypatch, "convert")

    monster_actions.execute_random_action(monster, ctx, rng=_FixedRng([0.0]))

    assert monster["ions"] == 1200
    assert all(entry.get("iid") != "pickup" for entry in monster["bag"])
    assert "pickup" not in monster_actions._picked_up_iids(monster)
    flash_messages = [text for _, text in bus.events if "blinding white flash" in text]
    assert flash_messages, "convert should emit the blinding white flash line"


def test_remove_broken_armour(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "goblin#1",
        "hp": {"current": 5, "max": 5},
        "stats": {"dex": 20},
        "derived": {"dex_bonus": 2, "armour_class": 2},
        "armour_slot": {"iid": "broken", "item_id": monster_actions.itemsreg.BROKEN_ARMOUR_ID},
    }
    bus = _DummyBus()
    ctx: Dict[str, Any] = {"feedback_bus": bus}

    monkeypatch.setattr(monster_actions, "_load_catalog", lambda: {})
    monkeypatch.setattr(monster_actions.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": monster_actions.itemsreg.BROKEN_ARMOUR_ID})

    _force_action(monkeypatch, "remove_armour")

    monster_actions.execute_random_action(monster, ctx, rng=_FixedRng([0.0]))

    assert monster.get("armour_slot") is None
    derived = monster.get("derived", {})
    assert derived.get("armour_class") == derived.get("dex_bonus")
    assert any("broken armour" in text.lower() for _, text in bus.events)


def test_monster_kill_player_transfers_loot(monkeypatch: pytest.MonkeyPatch) -> None:
    data: list[dict[str, Any]] = []

    def fake_cache() -> list[dict[str, Any]]:
        return data

    monkeypatch.setattr(monster_actions.itemsreg, "_cache", fake_cache)
    monkeypatch.setattr(monster_actions.itemsreg, "_save_instances_raw", lambda raw: None)
    monkeypatch.setattr(monster_actions.itemsreg, "save_instances", lambda: None)

    monster = {
        "id": "ogre#1",
        "hp": {"current": 10, "max": 10},
        "pos": [2000, 1, 1],
        "ions": 3,
        "riblets": 4,
    }

    stats = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
    hp = {"current": 1, "max": 20}
    active = {
        "id": "player#1",
        "class": "Thief",
        "pos": [2000, 1, 1],
        "stats": dict(stats),
        "hp": dict(hp),
        "inventory": ["dagger#1"],
        "bags": {"Thief": ["dagger#1"]},
        "bags_by_class": {"Thief": ["dagger#1"]},
        "equipment_by_class": {"Thief": {"armour": None}},
        "wielded_by_class": {"Thief": None},
        "ions": 15,
        "Ions": 15,
        "riblets": 9,
        "Riblets": 9,
    }
    state = {
        "players": [copy.deepcopy(active)],
        "active_id": "player#1",
        "active": copy.deepcopy(active),
        "inventory": ["dagger#1"],
        "bags": {"Thief": ["dagger#1"]},
        "bags_by_class": {"Thief": ["dagger#1"]},
        "equipment_by_class": {"Thief": {"armour": None}},
        "wielded_by_class": {"Thief": None},
        "stats_by_class": {"Thief": dict(stats)},
        "hp_by_class": {"Thief": dict(hp)},
        "ions_by_class": {"Thief": 15},
        "riblets_by_class": {"Thief": 9},
        "ions": 15,
        "riblets": 9,
        "Ions": 15,
        "Riblets": 9,
        "pos": [2000, 1, 1],
    }

    data.append({
        "iid": "dagger#1",
        "instance_id": "dagger#1",
        "item_id": "dagger",
        "enchant_level": 0,
        "condition": 80,
    })

    monkeypatch.setattr(monster_actions.pstate, "get_active_pair", lambda hint=None: (state, active))

    def fake_set_hp(st: Mapping[str, Any], hp_block: Mapping[str, Any]) -> Mapping[str, Any]:
        state["hp_by_class"]["Thief"] = dict(hp_block)
        state["active"]["hp"] = dict(hp_block)
        active["hp"] = dict(hp_block)
        return dict(hp_block)

    monkeypatch.setattr(monster_actions.pstate, "set_hp_for_active", fake_set_hp)
    monkeypatch.setattr(monster_actions.pstate, "save_state", lambda payload: None)
    monkeypatch.setattr(monster_actions.pstate, "clear_ready_target_for_active", lambda reason=None: None)
    monkeypatch.setattr(monster_actions.pstate, "get_ions_for_active", lambda st: int(st.get("ions", 0)))

    def _fake_set_ions(st: MutableMapping[str, Any], amount: int) -> int:
        value = int(amount)
        st["ions"] = value
        st.setdefault("Ions", value)
        ions_map = st.setdefault("ions_by_class", {})
        if isinstance(ions_map, MutableMapping):
            ions_map["Thief"] = value
        active_scope = st.setdefault("active", {})
        if isinstance(active_scope, MutableMapping):
            active_scope["ions"] = value
            active_scope["Ions"] = value
        return value

    monkeypatch.setattr(monster_actions.pstate, "set_ions_for_active", _fake_set_ions)
    monkeypatch.setattr(monster_actions.pstate, "get_riblets_for_active", lambda st: int(st.get("riblets", 0)))

    def _fake_set_riblets(st: MutableMapping[str, Any], amount: int) -> int:
        value = int(amount)
        st["riblets"] = value
        st.setdefault("Riblets", value)
        rib_map = st.setdefault("riblets_by_class", {})
        if isinstance(rib_map, MutableMapping):
            rib_map["Thief"] = value
        active_scope = st.setdefault("active", {})
        if isinstance(active_scope, MutableMapping):
            active_scope["riblets"] = value
            active_scope["Riblets"] = value
        return value

    monkeypatch.setattr(monster_actions.pstate, "set_riblets_for_active", _fake_set_riblets)

    monkeypatch.setattr(monster_actions.damage_engine, "compute_base_damage", lambda *args, **kwargs: 999)
    monkeypatch.setattr(monster_actions.items_wear, "wear_from_event", lambda payload: 0)
    monkeypatch.setattr(monster_actions, "_apply_weapon_wear", lambda *args, **kwargs: None)
    monkeypatch.setattr(monster_actions, "_load_catalog", lambda: {"dagger": {"name": "Dagger"}})

    bus = _DummyBus()
    ctx: Dict[str, Any] = {"feedback_bus": bus}

    assert monster_actions.pstate.get_ions_for_active(state) == 15
    assert monster_actions.pstate.get_riblets_for_active(state) == 9

    _force_action(monkeypatch, "attack")

    monster_actions.execute_random_action(monster, ctx, rng=_FixedRng([0.0]))

    assert monster.get("ions") == 18
    assert monster.get("riblets") == 13
    assert monster_actions.pstate.get_ions_for_active(state) == 0
    assert monster_actions.pstate.get_riblets_for_active(state) == 0
    assert state["inventory"] == []
    assert state["bags"]["Thief"] == []
    ground_items = monster_actions.itemsreg.list_instances_at(2000, 1, 1)
    assert any(inst.get("iid") == "dagger#1" for inst in ground_items)
    assert any(kind == "COMBAT/KILL" for kind, _ in bus.events)
