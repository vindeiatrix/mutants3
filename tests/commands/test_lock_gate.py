from __future__ import annotations

import copy
import pytest

from mutants.commands import lock as lock_cmd
from mutants.commands import open as open_cmd
from mutants.commands import unlock as unlock_cmd
from mutants.repl.dispatch import Dispatch
from mutants.registries.world import BASE_GATE
from mutants.registries import dynamics as dyn
from mutants.registries import items_instances as itemsreg, items_catalog


CAT = {
    "gate_key_a": {"key": True, "key_type": "gate_a"},
    "gate_key_b": {"key": True, "key_type": "gate_b"},
    "gate_key_generic": {"key": True},
}
INSTANCES = {
    "KA1": {"item_id": "gate_key_a"},
    "KB1": {"item_id": "gate_key_b"},
    "KG1": {"item_id": "gate_key_generic"},
}
CLASS_IDS = [
    "player_thief",
    "player_priest",
    "player_wizard",
    "player_warrior",
    "player_mage",
]


class DummyPlayerState:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data

    def to_dict(self) -> dict[str, object]:
        return self.data


class DummyStateManager:
    def __init__(self, players: list[dict[str, object]], active_id: str) -> None:
        self._order = [p["id"] for p in players]
        self._players: dict[str, DummyPlayerState] = {}
        for raw in players:
            pid = raw["id"]
            self._players[pid] = DummyPlayerState(copy.deepcopy(raw))
        self._active_id = active_id
        self.legacy_state = {
            "players": [self._players[cid].data for cid in self._order],
            "active_id": active_id,
        }

    def get_active(self) -> DummyPlayerState:
        return self._players[self._active_id]

    def switch_active(self, class_id: str) -> None:
        if class_id not in self._players:
            raise KeyError(class_id)
        self._active_id = class_id
        self.legacy_state["active_id"] = class_id

    def data_for(self, class_id: str) -> dict[str, object]:
        return self._players[class_id].data


class DummyBus:
    def __init__(self) -> None:
        self.msgs: list[tuple[str, str]] = []

    def push(self, chan: str, msg: str) -> None:
        self.msgs.append((chan, msg))


class DummyWorld:
    def __init__(self, edge: dict[str, object]) -> None:
        self._edge = edge
        self.saved = False

    def get_tile(self, x: int, y: int) -> dict[str, object]:
        return {"edges": {"S": self._edge}}

    def set_edge(self, x: int, y: int, D: str, *, gate_state=None, force_gate_base=False, key_type=None):
        if force_gate_base:
            self._edge["base"] = BASE_GATE
        if gate_state is not None:
            self._edge["gate_state"] = gate_state
        if key_type is not None:
            self._edge["key_type"] = key_type

    def save(self) -> None:
        self.saved = True


def mk_ctx_with_players(players: list[dict[str, object]], edge: dict[str, object], active_id: str | None = None):
    bus = DummyBus()
    world = DummyWorld(edge)
    state_mgr = DummyStateManager(players, active_id or players[0]["id"])
    ctx = {
        "feedback_bus": bus,
        "state_manager": state_mgr,
        "player_state": state_mgr.legacy_state,
        "world_loader": lambda year: world,
    }
    return world, ctx, bus, state_mgr


def mk_ctx(inv, edge):
    player = {"id": "player_thief", "pos": [2000, 0, 0], "inventory": list(inv)}
    return mk_ctx_with_players([player], edge, "player_thief")


def patch_items_and_dyn(monkeypatch):
    monkeypatch.setattr(items_catalog, "load_catalog", lambda: CAT)
    monkeypatch.setattr(itemsreg, "get_instance", lambda iid: INSTANCES.get(iid))

    locks: dict[tuple[int, int, int, str], dict[str, object]] = {}

    def _key(year, x, y, d):
        return (int(year), int(x), int(y), d)

    def get_lock(year, x, y, d):
        return locks.get(_key(year, x, y, d))

    def set_lock(year, x, y, d, lt):
        dx, dy = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}[d]
        opp = {"N": "S", "S": "N", "E": "W", "W": "E"}[d]
        locks[_key(year, x, y, d)] = {"locked": True, "lock_type": lt}
        locks[_key(year, x + dx, y + dy, opp)] = {"locked": True, "lock_type": lt}

    def clear_lock(year, x, y, d):
        dx, dy = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}[d]
        opp = {"N": "S", "S": "N", "E": "W", "W": "E"}[d]
        locks.pop(_key(year, x, y, d), None)
        locks.pop(_key(year, x + dx, y + dy, opp), None)

    monkeypatch.setattr(dyn, "get_lock", get_lock)
    monkeypatch.setattr(dyn, "set_lock", set_lock)
    monkeypatch.setattr(dyn, "clear_lock", clear_lock)
    return locks


def build_dispatch(ctx):
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])
    lock_cmd.register(dispatch, ctx)
    unlock_cmd.register(dispatch, ctx)
    open_cmd.register(dispatch, ctx)
    return dispatch


def run(dispatch, bus, cmd):
    pre = len(bus.msgs)
    token, *rest = cmd.split(" ", 1)
    arg = rest[0] if rest else ""
    dispatch.call(token, arg)
    return bus.msgs[pre:]


def test_lock_requires_key(monkeypatch):
    patch_items_and_dyn(monkeypatch)
    edge = {"base": BASE_GATE, "gate_state": 1}
    world, ctx, bus, state_mgr = mk_ctx([], edge)
    dispatch = build_dispatch(ctx)
    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/WARN", "You need a key to lock a gate.") in events
    assert dyn.get_lock(2000, 0, 0, "S") is None


def test_lock_open_or_non_gate_warns(monkeypatch):
    patch_items_and_dyn(monkeypatch)
    # Open gate
    edge = {"base": BASE_GATE, "gate_state": 0}
    world, ctx, bus, state_mgr = mk_ctx(["KA1"], edge)
    dispatch = build_dispatch(ctx)
    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/WARN", "You can only lock a closed gate.") in events
    # Non-gate
    edge2 = {"base": 0, "gate_state": 0}
    world2, ctx2, bus2, state_mgr2 = mk_ctx(["KA1"], edge2)
    dispatch2 = build_dispatch(ctx2)
    events2 = run(dispatch2, bus2, "lock south")
    assert ("SYSTEM/WARN", "You can only lock a closed gate.") in events2


def test_lock_prefixes_and_unlock_requires_matching_key(monkeypatch):
    patch_items_and_dyn(monkeypatch)
    edge = {"base": BASE_GATE, "gate_state": 1}
    world, ctx, bus, state_mgr = mk_ctx(["KA1"], edge)
    dispatch = build_dispatch(ctx)

    for tok in ["s", "so", "sou", "sout"]:
        events = run(dispatch, bus, f"loc {tok}")
        assert ("SYSTEM/OK", "You lock the gate south.") in events

    # Open should fail even with key
    events = run(dispatch, bus, "open south")
    assert ("SYSTEM/WARN", "The south gate is locked.") in events

    # No key
    state_mgr.data_for("player_thief")["inventory"] = []
    events = run(dispatch, bus, "unlock south")
    assert ("SYSTEM/WARN", "You don't have a key.") in events

    # Wrong key for unlock
    state_mgr.data_for("player_thief")["inventory"] = ["KB1"]
    events = run(dispatch, bus, "unlock south")
    assert ("SYSTEM/WARN", "That key doesn't fit.") in events

    # Correct key
    state_mgr.data_for("player_thief")["inventory"] = ["KA1"]
    events = run(dispatch, bus, "unlock south")
    assert ("SYSTEM/OK", "You unlock the gate south.") in events

    # Gate remains closed until opened
    events = run(dispatch, bus, "open south")
    assert ("SYSTEM/OK", "You've just opened the south gate.") in events
    assert world.saved is True
    assert edge["gate_state"] == 0
    assert dyn.get_lock(2000, 0, 0, "S") is None


def test_unlock_generic_key(monkeypatch):
    patch_items_and_dyn(monkeypatch)
    edge = {"base": BASE_GATE, "gate_state": 1}
    world, ctx, bus, state_mgr = mk_ctx(["KG1"], edge)
    dispatch = build_dispatch(ctx)

    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/OK", "You lock the gate south.") in events

    # Any key should unlock
    state_mgr.data_for("player_thief")["inventory"] = ["KB1"]
    events = run(dispatch, bus, "unlock south")
    assert ("SYSTEM/OK", "You unlock the gate south.") in events


@pytest.mark.parametrize("class_id", CLASS_IDS)
def test_lock_uses_active_player_inventory(monkeypatch, class_id):
    locks = patch_items_and_dyn(monkeypatch)
    edge = {"base": BASE_GATE, "gate_state": 1}
    players = [
        {"id": cid, "pos": [2000, idx * 2, -idx], "inventory": []}
        for idx, cid in enumerate(CLASS_IDS)
    ]
    world, ctx, bus, state_mgr = mk_ctx_with_players(players, edge, class_id)
    dispatch = build_dispatch(ctx)

    # Without a key the active class should fail to lock.
    locks.clear()
    edge["gate_state"] = 1
    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/WARN", "You need a key to lock a gate.") in events
    assert not locks

    # Give the active class a key and ensure the lock uses their coordinates.
    data = state_mgr.data_for(class_id)
    data["inventory"] = ["KA1"]
    locks.clear()
    edge["gate_state"] = 1
    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/OK", "You lock the gate south.") in events
    year, x, y = data.get("pos", [2000, 0, 0])
    assert locks.get((int(year), int(x), int(y), "S")) is not None

    # Switching to another class without a key should fail cleanly.
    for other in CLASS_IDS:
        if other == class_id:
            continue
        state_mgr.switch_active(other)
        bus.msgs.clear()
        locks.clear()
        edge["gate_state"] = 1
        state_mgr.data_for(other)["inventory"] = []
        events = run(dispatch, bus, "lock south")
        assert ("SYSTEM/WARN", "You need a key to lock a gate.") in events
        assert not locks
