from mutants.commands import travel as t


class Bus:
    def __init__(self) -> None:
        self.events = []

    def push(self, kind, msg):
        self.events.append((kind, msg))


class SM:
    def __init__(self) -> None:
        self.pos = [2000, 2, 2]

    def get_active(self):
        class P:
            def __init__(self, pos):
                self.data = {"pos": pos}

        return P(self.pos)

    def set_position(self, y, x, z):
        self.pos[:] = [y, x, z]


def test_travel_sets_origin_no_render():
    bus, sm = Bus(), SM()
    ctx = {"feedback_bus": bus, "state_manager": sm}
    t.travel_cmd("2100", ctx)
    assert sm.pos == [2100, 0, 0]
    assert any("Traveled to Year 2100" in msg for _, msg in bus.events)
