from __future__ import annotations

import copy
from typing import Any, Dict, List

import pytest

from mutants.commands import strike
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import damage_engine, player_state as pstate
from mutants.services.item_transfer import GROUND_CAP


class Bus:
    def __init__(self) -> None:
        self.msgs: List[tuple[str, str, Dict[str, Any]]] = []

    def push(self, kind: str, text: str, **meta: Any) -> None:
        self.msgs.append((kind, text, dict(meta)))


class DummyMonsters:
    def __init__(self, monsters: List[Dict[str, Any]]) -> None:
        self._monsters = {monster["id"]: monster for monster in monsters}
        self.killed: List[str] = []
        self.dirty_calls = 0

    def get(self, monster_id: str) -> Dict[str, Any] | None:
        return self._monsters.get(monster_id)

    def mark_dirty(self) -> None:
        self.dirty_calls += 1

    def kill_monster(self, monster_id: str) -> Dict[str, Any]:
        monster = self._monsters.pop(monster_id, None)
        if monster is None:
            return {"monster": None, "drops": [], "pos": None}
        hp = monster.setdefault("hp", {})
        if isinstance(hp, dict):
            hp["current"] = 0
        self.killed.append(monster_id)
        return {"monster": monster, "drops": [], "pos": monster.get("pos")}


def _base_state() -> Dict[str, Any]:
    stats = {"str": 10, "dex": 12, "int": 8, "wis": 9, "con": 11, "cha": 7}
    hp = {"current": 30, "max": 30}
    player = {
        "id": "p1",
        "name": "Thief",
        "class": "Thief",
        "pos": [2000, 1, 1],
        "stats": dict(stats),
        "hp": dict(hp),
        "inventory": [],
        "bags": {"Thief": []},
        "bags_by_class": {"Thief": []},
        "equipment_by_class": {"Thief": {"armour": None}},
        "wielded_by_class": {"Thief": None},
        "ready_target_by_class": {"Thief": None},
        "ready_target": None,
        "target_monster_id": None,
        "wielded": None,
        "armour": {"wearing": None},
        "ions": 0,
        "Ions": 0,
        "riblets": 0,
        "Riblets": 0,
        "exp_points": 0,
        "level": 1,
        "exhaustion": 0,
    }
    state = {
        "players": [copy.deepcopy(player)],
        "active_id": "p1",
        "active": copy.deepcopy(player),
        "inventory": [],
        "bags": {"Thief": []},
        "bags_by_class": {"Thief": []},
        "equipment_by_class": {"Thief": {"armour": None}},
        "wielded_by_class": {"Thief": None},
        "ready_target_by_class": {"Thief": None},
        "stats_by_class": {"Thief": dict(stats)},
        "hp_by_class": {"Thief": dict(hp)},
        "ions_by_class": {"Thief": 0},
        "riblets_by_class": {"Thief": 0},
        "exp_by_class": {"Thief": 0},
        "level_by_class": {"Thief": 1},
        "stats": dict(stats),
        "hp": dict(hp),
        "ions": 0,
        "Ions": 0,
        "riblets": 0,
        "Riblets": 0,
        "exp_points": 0,
        "level": 1,
        "exhaustion": 0,
        "wielded": None,
        "ready_target": None,
        "target_monster_id": None,
    }
    return state


def _make_monster(
    *,
    monster_id: str = "ogre#1",
    name: str = "Ogre",
    hp: int = 40,
    max_hp: int | None = None,
    ac: int = 10,
    armour_iid: str | None = None,
    armour_item: str = "chain_mail",
    armour_condition: int = 100,
    armour_enchant: int = 0,
) -> Dict[str, Any]:
    maximum = max_hp if max_hp is not None else hp
    monster = {
        "id": monster_id,
        "name": name,
        "hp": {"current": hp, "max": maximum},
        "stats": {"dex": 10},
        "derived": {"dex_bonus": 0, "armour_class": ac},
        "armour_slot": None,
    }
    if armour_iid is not None:
        monster["armour_slot"] = {
            "iid": armour_iid,
            "item_id": armour_item,
            "condition": armour_condition,
            "enchanted": "yes" if armour_enchant else "no",
            "enchant_level": armour_enchant,
            "derived": {"armour_class": ac},
        }
    return monster


@pytest.fixture
def in_memory_instances(monkeypatch):
    data: List[Dict[str, Any]] = []

    def fake_cache() -> List[Dict[str, Any]]:
        return data

    monkeypatch.setattr(itemsreg, "_cache", fake_cache)
    monkeypatch.setattr(itemsreg, "_save_instances_raw", lambda raw: None)
    monkeypatch.setattr(itemsreg, "save_instances", lambda: None)
    return data


@pytest.fixture
def strike_env(monkeypatch, in_memory_instances):
    state_store: Dict[str, Any] = {}

    def fake_load_state() -> Dict[str, Any]:
        return copy.deepcopy(state_store)

    def fake_save_state(new_state: Dict[str, Any]) -> None:
        state_store.clear()
        state_store.update(copy.deepcopy(new_state))

    monkeypatch.setattr(pstate, "load_state", fake_load_state)
    monkeypatch.setattr(pstate, "save_state", fake_save_state)

    catalog: Dict[str, Dict[str, Any]] = {}
    monkeypatch.setattr(items_catalog, "load_catalog", lambda: catalog)

    def setup(
        *,
        stats: Dict[str, int] | None = None,
        weapon: Dict[str, Any] | None = None,
        ready_target: str | None = None,
    ) -> None:
        base = _base_state()
        catalog.clear()
        catalog.update(
            {
                itemsreg.BROKEN_WEAPON_ID: {"name": "Broken Weapon", "base_power": 0},
                itemsreg.BROKEN_ARMOUR_ID: {"name": "Broken Armour", "armour": True, "armour_class": 0},
            }
        )
        in_memory_instances.clear()
        if stats:
            for key, value in stats.items():
                base["stats"][key] = value
                base["players"][0]["stats"][key] = value
                base["active"]["stats"][key] = value
                base["stats_by_class"]["Thief"][key] = value
        if weapon:
            iid = weapon["iid"]
            base["bags"]["Thief"].append(iid)
            base["inventory"].append(iid)
            base["players"][0]["bags"]["Thief"].append(iid)
            base["players"][0]["inventory"].append(iid)
            base["active"]["bags"]["Thief"].append(iid)
            base["active"]["inventory"].append(iid)
            base["wielded_by_class"]["Thief"] = {"wielded": iid}
            base["wielded"] = iid
            base["players"][0]["wielded_by_class"]["Thief"] = {"wielded": iid}
            base["players"][0]["wielded"] = iid
            base["active"]["wielded_by_class"]["Thief"] = {"wielded": iid}
            base["active"]["wielded"] = iid
            inst = {
                "iid": iid,
                "instance_id": iid,
                "item_id": weapon["item_id"],
                "enchanted": weapon.get("enchanted", "no"),
                "enchant_level": weapon.get("enchant_level", 0),
                "condition": weapon.get("condition", 100),
            }
            inst.update(weapon.get("extra", {}))
            in_memory_instances.append(inst)
            catalog[weapon["item_id"]] = {
                "name": weapon.get("name", weapon["item_id"].replace("_", " ").title()),
                "base_power": weapon.get("base_power", 0),
            }
        state_store.clear()
        state_store.update(copy.deepcopy(base))
        pstate.save_state(copy.deepcopy(base))
        if ready_target:
            pstate.set_ready_target_for_active(ready_target)

    return {
        "setup": setup,
        "state": state_store,
        "catalog": catalog,
        "instances": in_memory_instances,
    }


def test_strike_requires_ready_target(strike_env):
    strike_env["setup"]()
    bus = Bus()
    monsters = DummyMonsters([])
    ctx = {"feedback_bus": bus, "monsters": monsters}

    result = strike.strike_cmd("", ctx)

    assert result["ok"] is False
    assert result["reason"] == "no_target"
    assert any("not ready" in msg for _, msg, _ in bus.msgs)


def test_strike_weapon_damage_formula(strike_env, monkeypatch):
    strike_env["setup"](
        stats={"str": 500},
        weapon={
            "iid": "blade#1",
            "item_id": "ion_blade",
            "base_power": 10,
            "enchant_level": 3,
            "enchanted": "yes",
            "condition": 100,
            "name": "Ion Blade",
        },
        ready_target="ogre#1",
    )
    strike_env["catalog"].update({"plate": {"name": "Plate", "armour": True, "armour_class": 20}})
    monster = _make_monster(hp=200, max_hp=200, ac=20, armour_iid="ogre_armour", armour_item="plate")
    monsters = DummyMonsters([monster])
    bus = Bus()
    ctx = {"feedback_bus": bus, "monsters": monsters}
    state, active = pstate.get_active_pair()
    assert pstate.get_active_class(state) == "Thief"
    assert damage_engine.get_attacker_power("blade#1", active) == 72
    assert damage_engine.get_total_ac(monster) == 20
    assert damage_engine.compute_base_damage("blade#1", active, monster) == 52

    monkeypatch.setattr(pstate, "get_wielded_weapon_id", lambda payload=None: "blade#1")

    recorded: Dict[str, Any] = {}

    original_compute = strike.damage_engine.compute_base_damage

    def _recording_compute(item: Any, attacker: Any, defender: Any) -> int:
        value = original_compute(item, attacker, defender)
        recorded["raw"] = value
        recorded["item"] = item
        recorded["attacker"] = attacker
        recorded["defender"] = defender
        recorded["power"] = damage_engine.get_attacker_power(item, attacker)
        recorded["ac"] = damage_engine.get_total_ac(defender)
        return value

    monkeypatch.setattr(strike.damage_engine, "compute_base_damage", _recording_compute)

    result = strike.strike_cmd("", ctx)

    assert result["ok"] is True
    assert recorded["attacker"]["stats"]["str"] == 500
    assert damage_engine.get_attacker_power("blade#1", recorded["attacker"]) == 72
    assert damage_engine.get_total_ac(recorded["defender"]) == 20
    assert recorded.get("raw") == 52
    assert result["damage"] == 52
    assert monster["hp"]["current"] == 148
    assert any("You strike" in text and "52" in text for _, text, _ in bus.msgs)


def test_strike_innate_has_minimum_damage(strike_env):
    strike_env["setup"](stats={"str": 10}, ready_target="ogre#1")
    monster = _make_monster(ac=30)
    monsters = DummyMonsters([monster])
    bus = Bus()
    ctx = {"feedback_bus": bus, "monsters": monsters}

    result = strike.strike_cmd("", ctx)

    assert result["damage"] == 6
    assert monster["hp"]["current"] == monster["hp"]["max"] - 6
    assert any("6 damage" in text for _, text, _ in bus.msgs)


def test_strike_applies_wear_and_cracks_items(strike_env, monkeypatch):
    strike_env["setup"](
        stats={"str": 120},
        weapon={
            "iid": "rusty#1",
            "item_id": "rusty_blade",
            "base_power": 20,
            "enchant_level": 0,
            "enchanted": "no",
            "condition": 4,
            "name": "Rusty Blade",
        },
        ready_target="ogre#1",
    )
    strike_env["catalog"].update(
        {
            "rusty_blade": {"name": "Rusty Blade", "base_power": 20},
            "chain_mail": {"name": "Chain Mail", "armour": True, "armour_class": 10},
        }
    )
    strike_env["instances"].append(
        {
            "iid": "ogre_armour",
            "instance_id": "ogre_armour",
            "item_id": "chain_mail",
            "enchanted": "no",
            "enchant_level": 0,
            "condition": 3,
        }
    )
    monster = _make_monster(
        ac=10,
        armour_iid="ogre_armour",
        armour_item="chain_mail",
        armour_condition=3,
    )
    monsters = DummyMonsters([monster])
    bus = Bus()
    ctx = {"feedback_bus": bus, "monsters": monsters}
    monkeypatch.setattr(pstate, "get_wielded_weapon_id", lambda payload=None: "rusty#1")

    result = strike.strike_cmd("", ctx)

    assert result["damage"] > 0
    weapon_inst = itemsreg.get_instance("rusty#1")
    assert weapon_inst["item_id"] == itemsreg.BROKEN_WEAPON_ID
    armour_inst = itemsreg.get_instance("ogre_armour")
    assert armour_inst["item_id"] == itemsreg.BROKEN_ARMOUR_ID
    armour = monster["armour_slot"]
    assert armour["item_id"] == itemsreg.BROKEN_ARMOUR_ID
    assert armour["condition"] == 0
    assert monster["derived"]["armour_class"] == monster["derived"].get("dex_bonus", 0)
    crack_msgs = "\n".join(text for _, text, _ in bus.msgs)
    assert "Broken-Weapon" in crack_msgs
    assert "Broken-Armour" in crack_msgs or "Broken Armour" in crack_msgs


def test_strike_clamps_fatal_full_hp_blow(strike_env, monkeypatch):
    strike_env["setup"](
        stats={"str": 200},
        weapon={
            "iid": "greatsword#1",
            "item_id": "greatsword",
            "base_power": 80,
            "enchant_level": 0,
            "condition": 100,
            "name": "Greatsword",
        },
        ready_target="ogre#1",
    )
    strike_env["catalog"]["greatsword"] = {"name": "Greatsword", "base_power": 80}
    monster = _make_monster(hp=40, max_hp=40, ac=10)
    monsters = DummyMonsters([monster])
    bus = Bus()
    ctx = {"feedback_bus": bus, "monsters": monsters}

    monkeypatch.setattr(pstate, "get_wielded_weapon_id", lambda payload=None: "greatsword#1")

    result = strike.strike_cmd("", ctx)

    assert result["damage"] == 39
    assert monster["hp"]["current"] == 1
    assert all(kind != "COMBAT/KILL" for kind, _, _ in bus.msgs)


def test_strike_can_kill_when_target_weakened(strike_env, monkeypatch):
    strike_env["setup"](
        stats={"str": 160},
        weapon={
            "iid": "warhammer#1",
            "item_id": "warhammer",
            "base_power": 60,
            "enchant_level": 0,
            "condition": 100,
            "name": "Warhammer",
        },
        ready_target="ogre#1",
    )
    strike_env["catalog"]["warhammer"] = {"name": "Warhammer", "base_power": 60}
    monster = _make_monster(hp=20, max_hp=50, ac=5)
    monsters = DummyMonsters([monster])
    bus = Bus()
    ctx = {"feedback_bus": bus, "monsters": monsters}

    monkeypatch.setattr(pstate, "get_wielded_weapon_id", lambda payload=None: "warhammer#1")

    result = strike.strike_cmd("", ctx)

    assert result.get("killed") is True
    assert monsters.killed == ["ogre#1"]
    assert any(kind == "COMBAT/KILL" for kind, _, _ in bus.msgs)
    assert pstate.get_ready_target_for_active(pstate.load_state()) is None


def test_strike_kill_awards_currencies_and_drops_loot(strike_env, monkeypatch):
    strike_env["setup"](
        stats={"str": 200},
        weapon={
            "iid": "warhammer#1",
            "item_id": "warhammer",
            "base_power": 60,
            "enchant_level": 0,
            "condition": 100,
            "name": "Warhammer",
        },
        ready_target="ogre#1",
    )
    strike_env["catalog"].update(
        {
            "warhammer": {"name": "Warhammer", "base_power": 60},
            "club": {"name": "Club", "base_power": 5},
            "skull": {"name": "Skull"},
        }
    )
    monster = _make_monster(hp=6, max_hp=12, ac=0)
    monster.update({"pos": [2000, 1, 1], "ions": 12, "riblets": 7, "level": 3})

    drop_entry = {"item_id": "club", "condition": 55}

    class LootMonsters(DummyMonsters):
        def kill_monster(self, monster_id: str) -> Dict[str, Any]:
            summary = super().kill_monster(monster_id)
            monster_payload = summary.get("monster") if isinstance(summary, dict) else None
            pos = monster_payload.get("pos") if isinstance(monster_payload, dict) else None
            return {"monster": monster_payload or {}, "drops": [dict(drop_entry)], "pos": pos}

    monsters = LootMonsters([monster])
    bus = Bus()
    ctx = {"feedback_bus": bus, "monsters": monsters}

    monkeypatch.setattr(pstate, "get_wielded_weapon_id", lambda payload=None: "warhammer#1")

    result = strike.strike_cmd("", ctx)

    assert result.get("killed") is True
    state_after = pstate.load_state()
    assert pstate.get_ions_for_active(state_after) == 12
    assert pstate.get_riblets_for_active(state_after) == 7
    assert pstate.get_exp_for_active(state_after) == 300

    ground_items = itemsreg.list_instances_at(2000, 1, 1)
    item_ids = {inst.get("item_id") for inst in ground_items}
    assert "club" in item_ids and "skull" in item_ids
    assert any("crumbles to dust" in text for _, text, _ in bus.msgs)


def test_strike_kill_vaporizes_when_ground_full(strike_env, monkeypatch):
    strike_env["setup"](
        stats={"str": 200},
        weapon={
            "iid": "warhammer#1",
            "item_id": "warhammer",
            "base_power": 60,
            "enchant_level": 0,
            "condition": 100,
            "name": "Warhammer",
        },
        ready_target="ogre#1",
    )
    strike_env["catalog"].update(
        {
            "warhammer": {"name": "Warhammer", "base_power": 60},
            "club": {"name": "Club", "base_power": 5},
            "skull": {"name": "Skull"},
        }
    )
    for idx in range(GROUND_CAP):
        strike_env["instances"].append(
            {
                "iid": f"ground#{idx}",
                "instance_id": f"ground#{idx}",
                "item_id": f"junk{idx}",
                "pos": {"year": 2000, "x": 1, "y": 1},
                "year": 2000,
                "x": 1,
                "y": 1,
            }
        )
        strike_env["catalog"][f"junk{idx}"] = {"name": f"Junk {idx}"}

    monster = _make_monster(hp=6, max_hp=12, ac=0)
    monster.update({"pos": [2000, 1, 1], "ions": 5, "riblets": 3, "level": 2})

    class LootMonsters(DummyMonsters):
        def kill_monster(self, monster_id: str) -> Dict[str, Any]:
            summary = super().kill_monster(monster_id)
            monster_payload = summary.get("monster") if isinstance(summary, dict) else None
            pos = monster_payload.get("pos") if isinstance(monster_payload, dict) else None
            return {"monster": monster_payload or {}, "drops": [{"item_id": "club"}], "pos": pos}

    monsters = LootMonsters([monster])
    bus = Bus()
    ctx = {"feedback_bus": bus, "monsters": monsters}

    monkeypatch.setattr(pstate, "get_wielded_weapon_id", lambda payload=None: "warhammer#1")

    strike.strike_cmd("", ctx)

    ground_items = itemsreg.list_instances_at(2000, 1, 1)
    assert len(ground_items) == GROUND_CAP
    item_ids = {inst.get("item_id") for inst in ground_items}
    assert "club" not in item_ids and "skull" not in item_ids
    vapor_msgs = [text for _, text, _ in bus.msgs if "vaporizes" in text]
    assert vapor_msgs
