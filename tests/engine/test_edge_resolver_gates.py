from mutants.engine import edge_resolver as er
from mutants.registries.world import BASE_GATE, BASE_OPEN, GATE_OPEN, GATE_CLOSED


def mk_edge(base, gs=GATE_OPEN):
    return {"base": base, "gate_state": gs}


def test_open_gate_is_passable_both_sides():
    a, b = mk_edge(BASE_GATE, GATE_OPEN), mk_edge(BASE_GATE, GATE_OPEN)
    assert er._passable_pair(a, b) is True


def test_closed_gate_blocks():
    a, b = mk_edge(BASE_GATE, GATE_CLOSED), mk_edge(BASE_GATE, GATE_CLOSED)
    assert er._passable_pair(a, b) is False
    assert er._block_reason(a, b) == "closed_gate"


def test_one_sided_closed_gate_blocks_conservatively():
    a, b = mk_edge(BASE_GATE, GATE_CLOSED), mk_edge(BASE_OPEN, GATE_OPEN)
    assert er._passable_pair(a, b) is False
    assert er._block_reason(a, b) == "closed_gate"


def test_resolve_returns_reason_for_closed_gate():
    class DummyWorld:
        def __init__(self):
            self.tiles = {
                (0, 0): {"edges": {"N": mk_edge(BASE_GATE, GATE_CLOSED)}},
                (0, 1): {"edges": {"S": mk_edge(BASE_GATE, GATE_CLOSED)}},
            }

        def get_tile(self, year, x, y):  # pragma: no cover - simple dict lookup
            return self.tiles.get((x, y))

    dec = er.resolve(DummyWorld(), None, 2000, 0, 0, "N", actor={})
    assert dec.passable is False
    assert dec.reason == "closed_gate"
