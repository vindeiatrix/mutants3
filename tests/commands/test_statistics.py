from __future__ import annotations

from mutants.commands import inv, statistics


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


def test_statistics_pushes_summary(monkeypatch):
    bus = FakeBus()
    ctx = {"feedback_bus": bus, "state_manager": FakeStateManager()}
    monkeypatch.setattr(statistics, "get_player_inventory_instances", lambda _ctx: [])
    statistics.statistics_cmd("", ctx)
    lines = [text for _kind, text in bus.events]
    assert any(line.startswith("Name:") for line in lines)
    assert any("Hit Points" in line and "Level" in line for line in lines)
    assert any("Year A.D." in line for line in lines)


def test_statistics_inventory_section_matches_inventory_when_empty(monkeypatch):
    entries: list[str] = []
    monkeypatch.setattr(inv, "get_player_inventory_instances", lambda _ctx: list(entries))
    monkeypatch.setattr(statistics, "get_player_inventory_instances", lambda _ctx: list(entries))

    inv_bus = FakeBus()
    stat_bus = FakeBus()

    inv_ctx = {"feedback_bus": inv_bus}
    stat_ctx = {"feedback_bus": stat_bus}

    inv.inv_cmd("", inv_ctx)
    statistics.statistics_cmd("", stat_ctx)

    inv_lines = [text for _kind, text in inv_bus.events]
    stat_lines = [text for _kind, text in stat_bus.events]

    assert len(inv_lines) > 0
    assert stat_lines[-len(inv_lines) :] == inv_lines


def test_statistics_inventory_section_matches_inventory_when_populated(monkeypatch):
    entries = ["iid-1", "iid-2", "iid-3"]
    monkeypatch.setattr(inv, "get_player_inventory_instances", lambda _ctx: list(entries))
    monkeypatch.setattr(statistics, "get_player_inventory_instances", lambda _ctx: list(entries))

    catalog = {
        "test_sword": {"item_id": "test_sword", "weight": 2.6, "name": "Sword"},
        "test_potion": {"item_id": "test_potion", "weight": 0.5, "name": "Potion"},
    }
    instances = {
        "iid-1": {"item_id": "test_sword", "quantity": 1},
        "iid-2": {"item_id": "test_potion", "quantity": 2},
        "iid-3": {"item_id": "test_potion", "quantity": 1},
    }

    def loader():
        return catalog

    def resolver(iid: str):
        return dict(instances.get(iid, {}))

    inv_bus = FakeBus()
    stat_bus = FakeBus()

    inv_ctx = {
        "feedback_bus": inv_bus,
        "items_catalog_loader": loader,
        "items_instance_resolver": resolver,
    }
    stat_ctx = {
        "feedback_bus": stat_bus,
        "items_catalog_loader": loader,
        "items_instance_resolver": resolver,
    }

    inv.inv_cmd("", inv_ctx)
    statistics.statistics_cmd("", stat_ctx)

    inv_lines = [text for _kind, text in inv_bus.events]
    stat_lines = [text for _kind, text in stat_bus.events]

    assert len(inv_lines) > 0
    assert stat_lines[-len(inv_lines) :] == inv_lines
    assert inv_lines[0] == "You are carrying the following items: (Total Weight: 4 LB's)"
