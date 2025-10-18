from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.services import monster_ai
from mutants.services.combat_config import CombatConfig
from mutants.services.monster_ai import cascade as cascade_mod
from mutants.services.monster_ai.attack_selection import AttackPlan
from mutants.services.monster_actions import turnlog



class FakeRNG:
    def __init__(self, *, randrange_values: Sequence[int] | None = None, random_values: Sequence[float] | None = None) -> None:
        self._randrange = list(randrange_values or [])
        self._random = list(random_values or [])

    def randrange(self, stop: int) -> int:
        if not self._randrange:
            return 0
        value = self._randrange.pop(0)
        if stop <= 0:
            return 0
        return int(value) % int(stop)

    def random(self) -> float:
        if not self._random:
            return 0.0
        return float(self._random.pop(0))


class FakeLogSink:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def handle(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


class FakeBus:
    def __init__(self) -> None:
        self.messages: List[Tuple[str, str, Dict[str, Any]]] = []

    def push(self, kind: str, text: str, **meta: Any) -> None:
        self.messages.append((kind, text, dict(meta)))


class FakeMonsters:
    def __init__(self, entries: Sequence[MutableMapping[str, Any]]) -> None:
        self._entries = list(entries)
        self.mark_dirty_calls = 0

    def list_all(self) -> List[MutableMapping[str, Any]]:
        return list(self._entries)

    def list_at(self, year: int, x: int, y: int) -> List[MutableMapping[str, Any]]:
        result: List[MutableMapping[str, Any]] = []
        for entry in self._entries:
            pos = entry.get("pos")
            if isinstance(pos, Sequence) and len(pos) == 3:
                if int(pos[0]) == int(year) and int(pos[1]) == int(x) and int(pos[2]) == int(y):
                    result.append(entry)
        return result

    def mark_dirty(self) -> None:
        self.mark_dirty_calls += 1


class FakeScheduler:
    def __init__(self) -> None:
        self.bonus_actions: List[str] = []
        self.respawns: List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def queue_bonus_action(self, monster: Mapping[str, Any]) -> None:
        ident = str(monster.get("id") or monster.get("instance_id") or "?")
        self.bonus_actions.append(ident)

    def queue_player_respawn(self, player_id: str, monster: Mapping[str, Any], *, state: Mapping[str, Any], active: Mapping[str, Any]) -> None:
        self.respawns.append((player_id, dict(state), dict(active)))


class FakeWorld:
    def __init__(self) -> None:
        self.tiles: Dict[Tuple[int, int], Dict[str, Any]] = {}

    def add_passage(self, start: Tuple[int, int], end: Tuple[int, int]) -> None:
        sx, sy = start
        ex, ey = end
        dx, dy = ex - sx, ey - sy
        dir_code = { (1, 0): "E", (-1, 0): "W", (0, 1): "N", (0, -1): "S" }.get((dx, dy), "E")
        rev_code = {"E": "W", "W": "E", "N": "S", "S": "N"}[dir_code]
        self._ensure_tile(start)["edges"][dir_code] = {"base": 0, "gate_state": 0, "key_type": None, "spell_block": 0}
        self._ensure_tile(end)["edges"][rev_code] = {"base": 0, "gate_state": 0, "key_type": None, "spell_block": 0}

    def _ensure_tile(self, pos: Tuple[int, int]) -> Dict[str, Any]:
        if pos not in self.tiles:
            self.tiles[pos] = {"edges": {}}
        return self.tiles[pos]

    def get_tile(self, year: int, x: int, y: int) -> Optional[Dict[str, Any]]:
        return self.tiles.get((int(x), int(y)))


class FakeItemsRegistry:
    def __init__(self) -> None:
        self.instances: Dict[str, Dict[str, Any]] = {}
        self.positions: Dict[Tuple[int, int, int], List[str]] = defaultdict(list)
        self._counter = 0

    def _next_iid(self) -> str:
        self._counter += 1
        return f"iid-{self._counter}"

    def _key(self, year: int, x: int, y: int) -> Tuple[int, int, int]:
        return int(year), int(x), int(y)

    def seed_ground(self, pos: Tuple[int, int, int], item_id: str, *, iid: Optional[str] = None, enchant_level: int = 0) -> str:
        year, x, y = pos
        token = iid or self._next_iid()
        inst = {
            "iid": token,
            "item_id": item_id,
            "enchant_level": enchant_level,
            "origin": "world",
            "condition": 100,
        }
        inst["pos"] = {"year": year, "x": x, "y": y}
        self.instances[token] = inst
        key = self._key(year, x, y)
        if token not in self.positions[key]:
            self.positions[key].append(token)
        return token

    def list_instances_at(self, year: int, x: int, y: int) -> List[Dict[str, Any]]:
        key = self._key(year, x, y)
        return [self.instances[iid] for iid in list(self.positions.get(key, [])) if iid in self.instances]

    def get_instance(self, iid: str) -> Optional[Dict[str, Any]]:
        return self.instances.get(str(iid))

    def mint_instance(self, item_id: str, origin: str) -> str:
        iid = self._next_iid()
        self.instances[iid] = {"iid": iid, "item_id": item_id, "origin": origin, "enchant_level": 0}
        return iid

    def update_instance(self, iid: str, **updates: Any) -> None:
        inst = self.instances.setdefault(str(iid), {"iid": str(iid)})
        for key, value in updates.items():
            if value is None:
                inst.pop(key, None)
                continue
            inst[key] = value
        pos = inst.get("pos")
        if isinstance(pos, Mapping):
            try:
                year, x, y = int(pos["year"]), int(pos["x"]), int(pos["y"])
            except Exception:
                return
            key = self._key(year, x, y)
            if inst["iid"] not in self.positions[key]:
                self.positions[key].append(inst["iid"])

    def clear_position_at(self, iid: str, year: int, x: int, y: int) -> bool:
        key = self._key(year, x, y)
        if iid in self.positions.get(key, []):
            self.positions[key].remove(iid)
            inst = self.instances.get(iid)
            if inst is not None:
                inst.pop("pos", None)
            return True
        return False

    def move_instance(self, iid: str, dest: Tuple[int, int, int]) -> bool:
        inst = self.instances.get(iid)
        if inst is None:
            return False
        year, x, y = dest
        for key, entries in list(self.positions.items()):
            if iid in entries:
                entries.remove(iid)
        key = self._key(year, x, y)
        self.positions[key].append(iid)
        inst["pos"] = {"year": year, "x": x, "y": y}
        return True

    def remove_instance(self, iid: str) -> None:
        inst = self.instances.pop(iid, None)
        if inst is None:
            return
        pos = inst.get("pos")
        if isinstance(pos, Mapping):
            key = self._key(int(pos.get("year", 0)), int(pos.get("x", 0)), int(pos.get("y", 0)))
            if iid in self.positions.get(key, []):
                self.positions[key].remove(iid)

    def get_enchant_level(self, iid: str) -> int:
        inst = self.instances.get(iid)
        if inst is None:
            return 0
        try:
            return int(inst.get("enchant_level", 0))
        except Exception:
            return 0

    def ground_items(self, pos: Tuple[int, int, int]) -> List[Dict[str, Any]]:
        year, x, y = pos
        return self.list_instances_at(year, x, y)


class PlayerStateStub:
    def __init__(self) -> None:
        self.state: Dict[str, Any] = {
            "active_id": "player-1",
            "players": [
                {
                    "id": "player-1",
                    "pos": [2000, 0, 0],
                    "hp": {"current": 50, "max": 50},
                    "class": "psion",
                    "inventory": [],
                    "ions": 120,
                    "riblets": 75,
                }
            ],
            "pos": [2000, 0, 0],
            "ions_by_class": {"psion": 120},
            "riblets_by_class": {"psion": 75},
        }
        self.active = self.state["players"][0]
        self.clear_target_calls = 0

    def get_active_pair(self, state: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        return self.state, self.active

    def get_hp_for_active(self, state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return dict(self.active["hp"])

    def set_hp_for_active(self, state: Dict[str, Any], hp: Mapping[str, Any]) -> None:
        current = int(hp.get("current", self.active["hp"]["current"]))
        maximum = int(hp.get("max", self.active["hp"]["max"]))
        self.active["hp"] = {"current": current, "max": maximum}

    def get_ions_for_active(self, state: Optional[Dict[str, Any]]) -> int:
        return int(self.active.get("ions", 0))

    def get_riblets_for_active(self, state: Optional[Dict[str, Any]]) -> int:
        return int(self.active.get("riblets", 0))

    def get_active_class(self, state: Optional[Dict[str, Any]]) -> str:
        return "psion"

    def get_equipped_armour_id(self, state: Optional[Dict[str, Any]]) -> Optional[str]:
        return None

    def get_wielded_weapon_id(self, state: Optional[Dict[str, Any]]) -> Optional[str]:
        return None

    def clear_target(self, *, reason: Optional[str] = None) -> None:
        self.clear_target_calls += 1

    def set_position(self, pos: Sequence[int]) -> None:
        coords = [int(coord) for coord in pos]
        self.state["pos"] = list(coords)
        self.active["pos"] = list(coords)

    def set_hp(self, current: int, maximum: Optional[int] = None) -> None:
        max_hp = int(maximum) if maximum is not None else int(self.active["hp"]["max"])
        self.active["hp"] = {"current": int(current), "max": max_hp}

    def set_currency(self, *, ions: Optional[int] = None, riblets: Optional[int] = None) -> None:
        if ions is not None:
            self.active["ions"] = int(ions)
            self.state["ions_by_class"]["psion"] = int(ions)
        if riblets is not None:
            self.active["riblets"] = int(riblets)
            self.state["riblets_by_class"]["psion"] = int(riblets)


@dataclass
class RecordedCascade:
    token: str
    result: cascade_mod.ActionResult


class ScenarioHarness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.items = FakeItemsRegistry()
        self.world = FakeWorld()
        self.player_state = PlayerStateStub()
        self.bus = FakeBus()
        self.logsink = FakeLogSink()
        self.scheduler = FakeScheduler()
        self.monster: MutableMapping[str, Any] = {
            "id": "m-checklist",
            "name": "Checklist Fiend",
            "pos": [2000, 0, 0],
            "hp": {"current": 20, "max": 100},
            "ions": 400,
            "ions_max": 400,
            "level": 5,
            "bag": [],
            "target_player_id": "player-1",
            "stats": {"str": 12},
            "_ai_state": {"picked_up": [], "ledger": {"ions": 400, "riblets": 0}},
        }
        self.monsters = FakeMonsters([self.monster])
        self.turn_events: List[Tuple[str, Dict[str, Any]]] = []
        self.cascade_log: List[RecordedCascade] = []
        self.deposit_calls: List[Dict[str, int]] = []
        self.death_calls: List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
        self.pending_rng: Optional[FakeRNG] = None
        self.attack_plan = AttackPlan(source="innate", item_iid=None)
        self.attack_damage = 0
        self.catalog: Dict[str, Dict[str, Any]] = {
            "ion_shard": {"display": "Ion Shard", "convert_ions": 4000},
            "junk_rock": {"display": "Junk Rock", "convert_ions": 0},
        }
        self._install_patches()
        self.world.add_passage((0, 0), (1, 0))
        self.ctx: Dict[str, Any] = {
            "monsters": self.monsters,
            "player_state": self.player_state.state,
            "monster_ai_rng": FakeRNG(),
            "monster_wake_rng": FakeRNG(),
            "combat_config": CombatConfig(),
            "feedback_bus": self.bus,
            "logsink": self.logsink,
            "turn_scheduler": self.scheduler,
            "monster_ai_world_loader": lambda year: self.world,
        }

    def _install_patches(self) -> None:
        from mutants.registries import items_instances as itemsreg
        from mutants.services import combat_loot, damage_engine, items_wear, monsters_state, player_death, player_state as pstate
        from mutants.services.monster_ai import inventory as inventory_mod
        from mutants.services.monster_ai import pursuit as pursuit_mod
        from mutants.services.monster_ai import taunt as taunt_mod
        from mutants.ui import item_display, textutils
        from mutants.commands import convert as convert_cmd

        def fake_emit(ctx: Any, kind: str, *, message: str | None = None, **meta: Any) -> None:
            payload = dict(meta)
            if message is not None:
                payload["message"] = message
            self.turn_events.append((kind, payload))

        self.monkeypatch.setattr(turnlog, "emit", fake_emit)
        self.monkeypatch.setattr(itemsreg, "list_instances_at", self.items.list_instances_at)
        self.monkeypatch.setattr(itemsreg, "get_instance", self.items.get_instance)
        self.monkeypatch.setattr(itemsreg, "mint_instance", self.items.mint_instance)
        self.monkeypatch.setattr(itemsreg, "update_instance", self.items.update_instance)
        self.monkeypatch.setattr(itemsreg, "clear_position_at", self.items.clear_position_at)
        self.monkeypatch.setattr(itemsreg, "move_instance", self.items.move_instance)
        self.monkeypatch.setattr(itemsreg, "remove_instance", self.items.remove_instance)
        self.monkeypatch.setattr(itemsreg, "get_enchant_level", self.items.get_enchant_level)
        self.monkeypatch.setattr(monsters_state, "_refresh_monster_derived", lambda monster: None)
        self.monkeypatch.setattr(inventory_mod, "process_pending_drops", lambda monster, ctx, rng: None)
        self.monkeypatch.setattr(taunt_mod, "emit_taunt", lambda monster, bus, rng: {"ok": True, "message": None})
        self.monkeypatch.setattr(pursuit_mod, "attempt_pursuit", self._attempt_pursuit_stub)

        def fake_label(entry: Mapping[str, Any], template: Mapping[str, Any] | None = None, *, show_charges: bool = False) -> str:
            item_id = entry.get("item_id") if isinstance(entry, Mapping) else None
            if item_id:
                return str(item_id)
            if template and template.get("display"):
                return str(template["display"])
            return "item"

        self.monkeypatch.setattr(item_display, "item_label", fake_label)

        def fake_template(name: str, **values: Any) -> str:
            parts = [name]
            for key in sorted(values):
                parts.append(f"{key}={values[key]}")
            return "|".join(parts)

        self.monkeypatch.setattr(textutils, "render_feedback_template", fake_template)
        self.monkeypatch.setattr(textutils, "TEMPLATE_MONSTER_HEAL", "heal")
        self.monkeypatch.setattr(textutils, "TEMPLATE_MONSTER_HEAL_VISUAL", "heal-visual")
        self.monkeypatch.setattr(textutils, "TEMPLATE_MONSTER_CONVERT", "convert")
        self.monkeypatch.setattr(textutils, "TEMPLATE_MONSTER_MELEE_HIT", "melee-hit")
        self.monkeypatch.setattr(textutils, "TEMPLATE_MONSTER_RANGED_HIT", "ranged-hit")

        self.monkeypatch.setattr(combat_loot, "drop_existing_iids", lambda iids, pos: list(iids))
        self.monkeypatch.setattr(combat_loot, "enforce_capacity", lambda pos, drops, **kwargs: None)
        self.monkeypatch.setattr(combat_loot, "item_label", lambda entry, tpl, show_charges=False: entry.get("item_id", "item"))
        self.monkeypatch.setattr(combat_loot, "drop_monster_loot", lambda **kwargs: ([], []))

        def fake_resolve_attack(damage_item: Any, monster: Mapping[str, Any], target: Mapping[str, Any], *, source: str | None = None):
            class Attack:
                def __init__(self, amount: int, attack_source: str) -> None:
                    self.damage = amount
                    self.source = attack_source
            actual_source = source or self.attack_plan.source
            return Attack(self.attack_damage, actual_source)

        self.monkeypatch.setattr(damage_engine, "resolve_attack", fake_resolve_attack)
        self.monkeypatch.setattr(items_wear, "apply_wear", lambda *args, **kwargs: {})
        self.monkeypatch.setattr(items_wear, "wear_from_event", lambda event: 0)
        self.monkeypatch.setattr(items_wear, "build_wear_event", lambda **kwargs: {})

        def fake_select_attack(monster: Mapping[str, Any], ctx: Any) -> AttackPlan:
            return self.attack_plan

        from mutants.services import monster_actions

        import sys as _sys

        _sys.modules.setdefault("mutants.services.monster_ai.monster_actions", monster_actions)
        self.monkeypatch.setattr(monster_actions, "select_attack", fake_select_attack)

        original_eval = monster_actions.evaluate_cascade

        def capture_cascade(monster: Mapping[str, Any], ctx: Any) -> cascade_mod.ActionResult:
            result = original_eval(monster, ctx)
            token = getattr(self, "_current_token", "?")
            self.cascade_log.append(RecordedCascade(token=token, result=result))
            return result

        self.monkeypatch.setattr(monster_actions, "evaluate_cascade", capture_cascade)

        def fake_convert_value(item_id: str, catalog: Any, iid: Optional[str] = None) -> int:
            entry = self.catalog.get(str(item_id))
            if not entry:
                return 0
            return int(entry.get("convert_ions", 0))

        self.monkeypatch.setattr(convert_cmd, "_convert_value", fake_convert_value)

        self.monkeypatch.setattr(pstate, "get_active_pair", self.player_state.get_active_pair)
        self.monkeypatch.setattr(pstate, "get_hp_for_active", self.player_state.get_hp_for_active)
        self.monkeypatch.setattr(pstate, "set_hp_for_active", self.player_state.set_hp_for_active)
        self.monkeypatch.setattr(pstate, "get_ions_for_active", self.player_state.get_ions_for_active)
        self.monkeypatch.setattr(pstate, "get_riblets_for_active", self.player_state.get_riblets_for_active)
        self.monkeypatch.setattr(pstate, "get_active_class", self.player_state.get_active_class)
        self.monkeypatch.setattr(pstate, "get_equipped_armour_id", self.player_state.get_equipped_armour_id)
        self.monkeypatch.setattr(pstate, "get_wielded_weapon_id", self.player_state.get_wielded_weapon_id)
        self.monkeypatch.setattr(pstate, "clear_target", self.player_state.clear_target)

        def deposit(monster: MutableMapping[str, Any], *, ions: Any = 0, riblets: Any = 0) -> Dict[str, int]:
            amount = {"ions": int(ions), "riblets": int(riblets)}
            self.deposit_calls.append(amount)
            state = monster.setdefault("_ai_state", {}).setdefault("ledger", {"ions": 0, "riblets": 0})
            state["ions"] = state.get("ions", 0) + amount["ions"]
            state["riblets"] = state.get("riblets", 0) + amount["riblets"]
            monster["ions"] = state["ions"]
            monster["riblets"] = state["riblets"]
            return amount

        self.monkeypatch.setattr(player_death.monster_ledger, "deposit", deposit)

        def handle_player_death(player_id: str, monster: Mapping[str, Any], *, state: Mapping[str, Any], active: Mapping[str, Any]) -> None:
            self.death_calls.append((player_id, dict(state), dict(active)))

        self.monkeypatch.setattr(player_death, "handle_player_death", handle_player_death)
        self.monkeypatch.setattr(player_death, "monster_ledger", player_death.monster_ledger)

        self.monkeypatch.setattr("mutants.registries.items_catalog.load_catalog", lambda: self.catalog)

    def _attempt_pursuit_stub(self, monster: MutableMapping[str, Any], target: Sequence[int], rng: Any, *, ctx: Any = None, config: CombatConfig | None = None) -> bool:
        monster["pos"] = list(target)
        turnlog.emit(ctx, "AI/PURSUIT", monster=str(monster.get("id")), success=True, reason="stub")
        self.monsters.mark_dirty()
        return True

    def set_rng(self, *, randrange: Sequence[int], random: Sequence[float]) -> None:
        rng = FakeRNG(randrange_values=randrange, random_values=random)
        self.pending_rng = rng
        self.ctx["monster_ai_rng"] = rng
        self.ctx["monster_wake_rng"] = rng

    def advance(self, token: str, resolved: Optional[str] = None) -> None:
        self._current_token = token
        self.ctx["player_state"] = self.player_state.state
        if self.pending_rng is None:
            self.set_rng(randrange=[0], random=[0.6])
        monster_ai.on_player_command(self.ctx, token=token, resolved=resolved)
        self.pending_rng = None

    def pop_events(self) -> List[Tuple[str, Dict[str, Any]]]:
        events = list(self.turn_events)
        self.turn_events.clear()
        return events

    def pop_cascade(self) -> Optional[RecordedCascade]:
        if not self.cascade_log:
            return None
        return self.cascade_log.pop(0)

    def prepare_for_heal(self) -> None:
        self.monster["hp"] = {"current": 15, "max": 100}
        self.monster["ions"] = 5000
        self.monster["ions_max"] = 5000
        state = self.monster.setdefault("_ai_state", {})
        ledger = state.setdefault("ledger", {})
        ledger["ions"] = 5000
        ledger["riblets"] = ledger.get("riblets", 0)
        self.monster["bag"] = []
        state["picked_up"] = []

    def prepare_for_pickup(self) -> None:
        self.monster["hp"]["current"] = self.monster["hp"]["max"]
        self.monster["ions"] = 300
        self.monster["ions_max"] = 400
        state = self.monster.setdefault("_ai_state", {})
        state["picked_up"] = []
        state.setdefault("ledger", {})["ions"] = 300
        pos = (2000, 0, 0)
        self.items.seed_ground(pos, "junk_rock")
        shard_iid = self.items.seed_ground(pos, "ion_shard")
        state.setdefault("ledger", {})
        self._pickup_iid = shard_iid

    def prepare_for_convert(self) -> None:
        state = self.monster.setdefault("_ai_state", {})
        picked = state.setdefault("picked_up", [])
        if getattr(self, "_pickup_iid", None) and self._pickup_iid not in picked:
            picked.append(self._pickup_iid)
        self.monster["ions"] = 10
        self.monster["ions_max"] = 400
        state.setdefault("ledger", {})["ions"] = 10

    def prepare_for_pursuit(self, target: Sequence[int]) -> None:
        state = self.monster.setdefault("_ai_state", {})
        state["pending_pursuit"] = list(target)

    def prepare_for_kill(self, *, damage: int) -> None:
        state = self.monster.setdefault("_ai_state", {})
        state.pop("pending_pursuit", None)
        self.monster["ions"] = 0
        self.monster["ions_max"] = 0
        self.attack_damage = damage
        state.setdefault("ledger", {})["ions"] = 0
        self.player_state.set_hp(current=3, maximum=5)
        self.player_state.set_currency(ions=120, riblets=75)


@pytest.fixture
def scenario(monkeypatch: pytest.MonkeyPatch) -> ScenarioHarness:
    return ScenarioHarness(monkeypatch)


def _find_event(events: Iterable[Tuple[str, Dict[str, Any]]], kind: str) -> Optional[Dict[str, Any]]:
    for entry_kind, payload in events:
        if entry_kind == kind:
            return payload
    return None


def _failure_order(result: cascade_mod.ActionResult) -> List[str]:
    failures = result.data.get("failures") if isinstance(result.data, Mapping) else []
    order: List[str] = []
    if isinstance(failures, Iterable):
        for entry in failures:
            if isinstance(entry, Mapping) and isinstance(entry.get("gate"), str):
                order.append(entry["gate"])
    return order


def test_monster_ai_checklist_flow(scenario: ScenarioHarness) -> None:
    scenario.set_rng(randrange=[99], random=[0.9])
    scenario.advance(token="look", resolved="look")
    assert scenario.pop_events() == []
    assert scenario.pop_cascade() is None

    scenario.prepare_for_heal()
    scenario.set_rng(randrange=[0, 99, 0], random=[0.6])
    scenario.advance(token="login-entry", resolved="login-entry")
    heal_events = scenario.pop_events()
    heal_meta = _find_event(heal_events, "AI/ACT/HEAL")
    assert heal_meta is not None
    heal_result = scenario.pop_cascade()
    assert heal_result is not None
    assert heal_result.result.gate == "HEAL"
    assert _failure_order(heal_result.result) == ["FLEE"]

    scenario.prepare_for_pickup()
    scenario.set_rng(randrange=[0, 99, 99, 0], random=[0.6])
    scenario.advance(token="look", resolved="look")
    pickup_events = scenario.pop_events()
    pickup_meta = _find_event(pickup_events, "AI/ACT/PICKUP")
    assert pickup_meta is not None
    assert pickup_meta.get("item_id") == "ion_shard"
    ground_items = {inst.get("item_id") for inst in scenario.items.ground_items((2000, 0, 0))}
    assert "junk_rock" in ground_items
    pickup_result = scenario.pop_cascade()
    assert pickup_result is not None
    assert pickup_result.result.gate == "PICKUP"
    assert _failure_order(pickup_result.result) == ["FLEE", "HEAL", "CONVERT", "CAST", "ATTACK"]

    scenario.prepare_for_convert()
    scenario.set_rng(randrange=[0, 0], random=[0.6])
    scenario.advance(token="look", resolved="look")
    convert_events = scenario.pop_events()
    convert_meta = _find_event(convert_events, "AI/ACT/CONVERT")
    assert convert_meta is not None
    assert convert_meta.get("ions") == 4000
    convert_result = scenario.pop_cascade()
    assert convert_result is not None
    assert convert_result.result.gate == "CONVERT"
    assert _failure_order(convert_result.result) == ["FLEE", "HEAL"]
    assert scenario.monster.get("ions") == 4010
    assert not scenario.monster.get("bag")

    scenario.prepare_for_pursuit([2000, 1, 0])
    scenario.set_rng(randrange=[0], random=[0.6])
    scenario.advance(token="look", resolved="look")
    pursuit_events = scenario.pop_events()
    pursuit_meta = _find_event(pursuit_events, "AI/PURSUIT")
    assert pursuit_meta is not None and pursuit_meta.get("success") is True
    assert scenario.monster["pos"] == [2000, 1, 0]
    assert scenario.monsters.mark_dirty_calls > 0
    assert scenario.pop_cascade() is None

    scenario.player_state.set_position([2000, 1, 0])
    scenario.prepare_for_kill(damage=999)
    scenario.set_rng(randrange=[0, 0], random=[0.6])
    scenario.advance(token="look", resolved="look")
    kill_events = scenario.pop_events()
    attack_meta = _find_event(kill_events, "AI/ACT/ATTACK")
    assert attack_meta is not None and attack_meta.get("killed") is True
    kill_meta = _find_event(kill_events, "COMBAT/KILL")
    assert kill_meta is not None and kill_meta.get("victim") == "player-1"
    assert scenario.scheduler.bonus_actions == ["m-checklist"]
    assert scenario.deposit_calls and scenario.deposit_calls[-1]["ions"] == 120
    assert scenario.scheduler.respawns and scenario.scheduler.respawns[-1][0] == "player-1"
    assert scenario.player_state.active["hp"]["current"] == 0
