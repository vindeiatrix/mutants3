import types

from mutants.commands import lock as lock_cmd
from mutants.commands import open as open_cmd
from mutants.commands import unlock as unlock_cmd
from mutants.repl.dispatch import Dispatch
from mutants.registries.world import BASE_GATE
from mutants.registries import dynamics as dyn
from mutants.registries import items_instances as itemsreg, items_catalog
from mutants.engine import edge_resolver as ER


class DummyWorld:
    def __init__(self, edge):
        self._edge = edge
        self.saved = False

    def get_tile(self, x, y):
        if y == 0:
            return {"edges": {"S": self._edge}}
        if y == -1:
            return {"edges": {"N": self._edge}}
        return {"edges": {}}

    def set_edge(self, x, y, D, *, gate_state=None, force_gate_base=False, key_type=None):
        if force_gate_base:
            self._edge["base"] = BASE_GATE
        if gate_state is not None:
            self._edge["gate_state"] = gate_state
        if key_type is not None:
            self._edge["key_type"] = key_type

    def save(self):
        self.saved = True


def mk_ctx(inv, edge, monkeypatch):
    bus = types.SimpleNamespace(msgs=[])

    def push(chan, msg):
        bus.msgs.append((chan, msg))

    bus.push = push
    world = DummyWorld(edge)
    ctx = {
        "feedback_bus": bus,
        "player_state": {
            "active_id": 1,
            "players": [{"id": 1, "pos": [2000, 0, 0], "inventory": list(inv)}],
        },
        "world_loader": lambda year: world,
    }
    # ensure commands see this test inventory via live loader
    monkeypatch.setattr(lock_cmd.it, "_load_player", lambda: {"inventory": ctx["player_state"]["players"][0]["inventory"]})
    monkeypatch.setattr(unlock_cmd.it, "_load_player", lambda: {"inventory": ctx["player_state"]["players"][0]["inventory"]})
    return world, ctx, bus


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


def patch_items_and_dyn(monkeypatch):
    monkeypatch.setattr(items_catalog, "load_catalog", lambda: CAT)
    monkeypatch.setattr(itemsreg, "get_instance", lambda iid: INSTANCES.get(iid))

    locks = {}

    def _key(year, x, y, d):
        return (year, x, y, d)

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
    world, ctx, bus = mk_ctx([], edge, monkeypatch)
    dispatch = build_dispatch(ctx)
    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/WARN", "You need a key to lock a gate.") in events
    assert dyn.get_lock(2000, 0, 0, "S") is None


def test_lock_open_or_non_gate_warns(monkeypatch):
    patch_items_and_dyn(monkeypatch)
    # Open gate
    edge = {"base": BASE_GATE, "gate_state": 0}
    world, ctx, bus = mk_ctx(["KA1"], edge, monkeypatch)
    dispatch = build_dispatch(ctx)
    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/WARN", "You can only lock a closed gate.") in events
    assert dyn.get_lock(2000, 0, 0, "S") is None
    # Non-gate
    edge2 = {"base": 0, "gate_state": 0}
    world2, ctx2, bus2 = mk_ctx(["KA1"], edge2, monkeypatch)
    dispatch2 = build_dispatch(ctx2)
    events2 = run(dispatch2, bus2, "lock south")
    assert ("SYSTEM/WARN", "You can only lock a closed gate.") in events2
    assert dyn.get_lock(2000, 0, 0, "S") is None
    # Weird state should warn via not_closed
    edge3 = {"base": BASE_GATE, "gate_state": 5}
    world3, ctx3, bus3 = mk_ctx(["KA1"], edge3, monkeypatch)
    dispatch3 = build_dispatch(ctx3)
    events3 = run(dispatch3, bus3, "lock south")
    assert ("SYSTEM/WARN", "You can only lock a closed gate.") in events3
    assert dyn.get_lock(2000, 0, 0, "S") is None


def test_lock_rejects_when_already_locked(monkeypatch):
    patch_items_and_dyn(monkeypatch)
    edge = {"base": BASE_GATE, "gate_state": 1}
    world, ctx, bus = mk_ctx(["KA1"], edge, monkeypatch)
    dispatch = build_dispatch(ctx)

    # Pre-existing dynamic lock
    dyn.set_lock(2000, 0, 0, "S", "gate_a")
    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/WARN", "That gate is already locked.") in events
    lock = dyn.get_lock(2000, 0, 0, "S")
    assert lock and lock.get("lock_type") == "gate_a"

    # Static locked gate_state should also warn
    dyn.clear_lock(2000, 0, 0, "S")
    edge["gate_state"] = 2
    events2 = run(dispatch, bus, "lock south")
    assert ("SYSTEM/WARN", "That gate is already locked.") in events2


def test_lock_sets_dynamic_lock_and_resolver_reports_locked(monkeypatch):
    patch_items_and_dyn(monkeypatch)
    edge = {"base": BASE_GATE, "gate_state": 1}
    world, ctx, bus = mk_ctx(["KA1"], edge, monkeypatch)
    dispatch = build_dispatch(ctx)

    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/OK", "You lock the gate south.") in events

    lock_meta = dyn.get_lock(2000, 0, 0, "S")
    assert lock_meta == {"locked": True, "lock_type": "gate_a"}
    neighbor_lock = dyn.get_lock(2000, 0, -1, "N")
    assert neighbor_lock == lock_meta
    assert edge["gate_state"] == 1

    dec = ER.resolve(world, dyn, 2000, 0, 0, "S", actor={})
    assert dec.passable is False
    assert dec.reason == "closed_gate"
    assert any(tag == "lock" for tag, _ in dec.reason_chain)


def test_lock_prefixes_and_unlock_requires_matching_key(monkeypatch):
    patch_items_and_dyn(monkeypatch)
    edge = {"base": BASE_GATE, "gate_state": 1}
    world, ctx, bus = mk_ctx(["KA1"], edge, monkeypatch)
    dispatch = build_dispatch(ctx)

    tokens = ["s", "so", "sou", "sout"]
    for idx, tok in enumerate(tokens):
        events = run(dispatch, bus, f"loc {tok}")
        assert ("SYSTEM/OK", "You lock the gate south.") in events
        lock_meta = dyn.get_lock(2000, 0, 0, "S")
        assert lock_meta and lock_meta.get("lock_type") == "gate_a"
        if idx < len(tokens) - 1:
            events = run(dispatch, bus, "unlock south")
            assert ("SYSTEM/OK", "You unlock the gate south.") in events
            assert dyn.get_lock(2000, 0, 0, "S") is None

    lock_meta = dyn.get_lock(2000, 0, 0, "S")
    assert lock_meta and lock_meta.get("lock_type") == "gate_a"

    # Open should fail even with key
    events = run(dispatch, bus, "open south")
    assert ("SYSTEM/WARN", "The south gate is locked.") in events
    assert dyn.get_lock(2000, 0, 0, "S") == lock_meta

    # No key
    ctx["player_state"]["players"][0]["inventory"] = []
    events = run(dispatch, bus, "unlock south")
    assert ("SYSTEM/WARN", "You don't have a key.") in events
    assert dyn.get_lock(2000, 0, 0, "S") == lock_meta

    # Wrong key for unlock
    ctx["player_state"]["players"][0]["inventory"] = ["KB1"]
    events = run(dispatch, bus, "unlock south")
    assert ("SYSTEM/WARN", "That key doesn't fit.") in events
    assert dyn.get_lock(2000, 0, 0, "S") == lock_meta

    # Correct key
    ctx["player_state"]["players"][0]["inventory"] = ["KA1"]
    events = run(dispatch, bus, "unlock south")
    assert ("SYSTEM/OK", "You unlock the gate south.") in events
    assert dyn.get_lock(2000, 0, 0, "S") is None

    # Gate remains closed until opened
    events = run(dispatch, bus, "open south")
    assert ("SYSTEM/OK", "You've just opened the south gate.") in events
    assert world.saved is True
    assert edge["gate_state"] == 0
    assert dyn.get_lock(2000, 0, 0, "S") is None


def test_unlock_generic_key(monkeypatch):
    patch_items_and_dyn(monkeypatch)
    edge = {"base": BASE_GATE, "gate_state": 1}
    world, ctx, bus = mk_ctx(["KG1"], edge, monkeypatch)
    dispatch = build_dispatch(ctx)

    events = run(dispatch, bus, "lock south")
    assert ("SYSTEM/OK", "You lock the gate south.") in events
    lock_meta = dyn.get_lock(2000, 0, 0, "S")
    assert lock_meta == {"locked": True, "lock_type": ""}

    # Any key should unlock
    ctx["player_state"]["players"][0]["inventory"] = ["KB1"]
    events = run(dispatch, bus, "unlock south")
    assert ("SYSTEM/OK", "You unlock the gate south.") in events

