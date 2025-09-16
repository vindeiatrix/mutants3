from __future__ import annotations

from mutants.commands import statistics


class FakeBus:
    def __init__(self):
        self.events = []

    def push(self, kind, text):
        self.events.append((kind, text))


class FakePlayer:
    def __init__(self):
        self.data = {
            "name": "Thief",
            "class": "Thief",
            "level": 1,
            "exp_points": 0,
            "hp": {"current": 10, "max": 12},
            "armour": {"armour_class": 2},
            "ions": 123,
            "riblets": 4,
            "stats": {"str": 10, "int": 9, "wis": 8, "dex": 11, "con": 12, "cha": 13},
            "conditions": {"poisoned": False, "encumbered": True, "ion_starving": False},
            "pos": [2000, 1, -2],
        }

    def to_dict(self):
        return self.data


class FakeStateManager:
    def __init__(self):
        self.player = FakePlayer()

    def get_active(self):
        return self.player


def test_statistics_pushes_summary():
    bus = FakeBus()
    ctx = {"feedback_bus": bus, "state_manager": FakeStateManager()}
    statistics.statistics_cmd("", ctx)
    lines = [text for _kind, text in bus.events]
    assert any(line.startswith("Name:") for line in lines)
    assert any("Hit Points" in line and "Level" in line for line in lines)
    assert any("Year A.D." in line for line in lines)
