from mutants.commands import statistics as stat


class Bus:
    def __init__(self):
        self.events = []

    def push(self, key, string):
        self.events.append((key, string))


class FakeItems:
    def describe(self, iid):
        return {"name": f"Item {iid}", "weight_lb": 2}


class SM:
    def __init__(self):
        self.p = {
            "name": "Gwydion",
            "class": "Thief",
            "level": 1,
            "exp_points": 0,
            "hp": {"current": 18, "max": 18},
            "ions": 30000,
            "riblets": 0,
            "stats": {"str": 15, "int": 9, "wis": 8, "dex": 14, "con": 15, "cha": 16},
            "conditions": {"poisoned": False},
            "armour": {"armour_class": 1},
            "pos": [2000, 0, 0],
            "inventory": ["i1", "i2"],
        }

    def get_active(self):
        class P:
            def __init__(self, data):
                self._data = data

            def to_dict(self):
                return self._data

        return P(self.p)


def test_statistics_renders_core_lines(monkeypatch):
    bus = Bus()
    sm = SM()
    ctx = {"feedback_bus": bus, "state_manager": sm, "items": FakeItems()}
    monkeypatch.setattr(stat, "get_player_inventory_instances", lambda _ctx: [])
    stat.statistics_cmd("", ctx)
    out = [text for _, text in bus.events]
    assert any(line.startswith("Name:") for line in out)
    assert any("Exhaustion" in line for line in out)
    assert any("Hit Points" in line and "Level" in line for line in out)
    assert any("Year A.D." in line for line in out)
    assert any("You are carrying the following items" in line for line in out)
    assert any("Total Weight:" in line for line in out)
