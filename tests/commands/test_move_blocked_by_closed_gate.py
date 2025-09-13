import types

from mutants.commands.move import move
from mutants.registries.world import BASE_GATE, GATE_CLOSED, GATE_OPEN


class DummyWorld:
    def __init__(self, cur_edge, nbr_edge):
        self.cur_edge = cur_edge
        self.nbr_edge = nbr_edge

    def get_tile(self, year, x, y):
        if (x, y) == (0, 0):
            return {"edges": {"W": self.cur_edge}}
        if (x, y) == (-1, 0):
            return {"edges": {"E": self.nbr_edge}}
        return {"edges": {}}


def mk_ctx(cur_edge, nbr_edge):
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
        "render_next": False,
    }
    return ctx, bus


def test_move_blocked_message():
    cur = {"base": BASE_GATE, "gate_state": GATE_CLOSED}
    nbr = {"base": BASE_GATE, "gate_state": GATE_CLOSED}
    ctx, bus = mk_ctx(cur, nbr)
    move("W", ctx)
    assert ("MOVE/BLOCKED", "The west gate is closed.") in bus.msgs
    # ensure player did not move
    p = ctx["player_state"]["players"][0]
    assert p["pos"] == [2000, 0, 0]
