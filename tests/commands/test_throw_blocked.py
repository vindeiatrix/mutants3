import types

from mutants.commands.throw import throw_cmd
from mutants.registries.world import BASE_GATE, GATE_CLOSED, GATE_OPEN, BASE_BOUNDARY
from mutants.services import item_transfer
from mutants.ui import item_display as idisp
from mutants.registries import items_instances as itemsreg


class DummyWorld:
    def __init__(self, cur_edge, nbr_edge):
        self.cur_edge = cur_edge
        self.nbr_edge = nbr_edge

    def get_tile(self, year, x, y):
        if (x, y) == (0, 0):
            return {"edges": {"N": self.cur_edge}}
        if (x, y) == (0, 1):
            return {"edges": {"S": self.nbr_edge}}
        return {"edges": {}}


def mk_ctx(cur_edge, nbr_edge, player):
    bus = types.SimpleNamespace(msgs=[])

    def push(chan, msg):
        bus.msgs.append((chan, msg))

    bus.push = push
    world = DummyWorld(cur_edge, nbr_edge)
    ctx = {
        "feedback_bus": bus,
        "player_state": {
            "active_id": 1,
            "players": [{"id": 1, "pos": [2000, 0, 0]}],
        },
        "world_loader": lambda year: world,
    }
    return ctx, bus


def patch_items(monkeypatch, player):
    monkeypatch.setattr(item_transfer, "_load_player", lambda: player)
    monkeypatch.setattr(item_transfer, "_save_player", lambda p: None)
    positions = {}
    monkeypatch.setattr(itemsreg, "set_position", lambda iid, yr, x, y: positions.update({iid: (yr, x, y)}))
    monkeypatch.setattr(itemsreg, "clear_position", lambda iid: positions.pop(iid, None))
    monkeypatch.setattr(itemsreg, "list_instances_at", lambda yr, x, y: [])
    monkeypatch.setattr(itemsreg, "save_instances", lambda: None)
    monkeypatch.setattr(itemsreg, "get_instance", lambda iid: None)
    monkeypatch.setattr(idisp, "canonical_name_from_iid", lambda iid: iid)
    return positions


def test_throw_blocked_no_exit_keeps_item(monkeypatch):
    cur = {"base": BASE_BOUNDARY}
    nbr = {"base": BASE_BOUNDARY}
    player = {"inventory": ["rock"], "armor": None}
    ctx, bus = mk_ctx(cur, nbr, player)
    positions = patch_items(monkeypatch, player)

    throw_cmd("north rock", ctx)

    assert "rock" in player["inventory"]
    assert not positions
    assert any("No exit" in m for _, m in bus.msgs)


def test_throw_blocked_closed_gate(monkeypatch):
    cur = {"base": BASE_GATE, "gate_state": GATE_CLOSED}
    nbr = {"base": BASE_GATE, "gate_state": GATE_CLOSED}
    player = {"inventory": ["rock"], "armor": None}
    ctx, bus = mk_ctx(cur, nbr, player)
    positions = patch_items(monkeypatch, player)

    throw_cmd("north rock", ctx)

    assert "rock" in player["inventory"]
    assert not positions
    assert any("gate is closed" in m for _, m in bus.msgs)


def test_throw_open_succeeds(monkeypatch):
    cur = {"base": BASE_GATE, "gate_state": GATE_OPEN}
    nbr = {"base": BASE_GATE, "gate_state": GATE_OPEN}
    player = {"inventory": ["rock"], "armor": None}
    ctx, bus = mk_ctx(cur, nbr, player)
    positions = patch_items(monkeypatch, player)

    throw_cmd("north rock", ctx)

    assert "rock" not in player["inventory"]
    assert positions.get("rock") == (2000, 0, -1)
    assert any("You throw" in m for _, m in bus.msgs)
