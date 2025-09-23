import pytest

from mutants.commands import mon
from mutants.ui.feedback import FeedbackBus


class _DummyMonsters:
    def __init__(self, monster):
        self._monster = monster

    def get(self, monster_id):
        return self._monster if monster_id == self._monster["id"] else None

    def list_all(self):
        return [self._monster]


@pytest.fixture
def monster_record():
    return {
        "id": "ogre#1",
        "name": "Ogre",
        "level": 5,
        "hp": {"current": 10, "max": 20},
        "stats": {"str": 30, "dex": 12, "con": 18, "int": 4, "wis": 6, "cha": 3},
        "pinned_years": [2000, 2100],
        "wielded": "ogre#club",
        "armour_slot": {"item_id": "leather_mail", "iid": "ogre#mail"},
        "bag": [{"item_id": "club"}, {"item_id": "potion"}],
    }


def test_mon_debug_outputs_expected_fields(monster_record):
    monsters = _DummyMonsters(monster_record)
    bus = FeedbackBus()
    ctx = {"monsters": monsters, "feedback_bus": bus}

    mon.mon_cmd("debug ogre#1", ctx)

    events = bus.drain()
    assert events
    event = events[-1]
    assert event["kind"] == "DEBUG"
    text = event["text"]
    assert "id=ogre#1" in text
    assert "name=Ogre" in text
    assert "level=5" in text
    assert "hp=10/20" in text
    assert "stats=str:30" in text
    assert "pinned=2000,2100" in text
    assert "wielded=ogre#club" in text
    assert "armour=leather_mail" in text
    assert "bag=2" in text


def test_mon_unknown_monster(monster_record):
    monsters = _DummyMonsters(monster_record)
    bus = FeedbackBus()
    ctx = {"monsters": monsters, "feedback_bus": bus}

    mon.mon_cmd("debug missing", ctx)

    events = bus.drain()
    assert events
    event = events[-1]
    assert event["kind"] == "SYSTEM/WARN"
    assert "Unknown monster" in event["text"]
