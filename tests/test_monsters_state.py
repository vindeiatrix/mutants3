import json

import pytest

from mutants.services import monsters_state


@pytest.fixture(autouse=True)
def _clear_cache():
    monsters_state.invalidate_cache()
    yield
    monsters_state.invalidate_cache()


def _write_state(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_state_normalizes_monster_records(tmp_path, monkeypatch):
    catalog = {
        "rust_sword": {"item_id": "rust_sword", "base_power": 5, "weight": 40},
        "leather": {"item_id": "leather", "armour": True, "armour_class": 3, "weight": 15},
    }
    monkeypatch.setattr(monsters_state.items_catalog, "load_catalog", lambda: catalog)

    monsters_payload = {
        "monsters": [
            {
                "id": "ghoul#1",
                "name": "Ghoul",
                "level": "3",
                "stats": {"str": "21", "dex": "12", "wis": 0},
                "hp": {"current": "15", "max": "20"},
                "bag": [
                    {"item_id": "rust_sword", "enchant_level": "2", "condition": 55},
                    {"item_id": "leather", "iid": "leather#bag", "condition": 40},
                ],
                "armour_slot": {"item_id": "leather", "iid": "leather#bag", "condition": 70, "enchant_level": 1},
                "wielded": "rust_sword",
                "pinned_years": ["2000", 2000, 2100, "2100"],
                "pos": ["2000", "1", "-2"],
                "notes": 123,
            }
        ]
    }

    path = tmp_path / "instances.json"
    _write_state(path, monsters_payload)

    state = monsters_state.load_state(path)
    monsters = state.list_all()

    assert len(monsters) == 1
    monster = monsters[0]

    assert monster["id"] == "ghoul#1"
    assert monster["hp"] == {"current": 15, "max": 20}
    assert monster["pinned_years"] == [2000, 2100]
    assert monster["pos"] == [2000, 1, -2]
    assert monster["notes"] == "123"

    bag = monster["bag"]
    assert len(bag) == 1
    weapon = bag[0]
    assert weapon["item_id"] == "rust_sword"
    assert weapon["condition"] == 100  # enchanted items are non-degrading
    assert weapon["derived"]["effective_weight"] == 20
    assert weapon["derived"]["base_damage"] == 13

    armour = monster["armour_slot"]
    assert armour is not None
    assert armour["iid"] == "leather#bag"
    assert armour["condition"] == 100
    assert armour["derived"]["armour_class"] == 4

    assert monster["wielded"] == weapon["iid"]

    derived = monster["derived"]
    assert derived["armour_class"] == 5  # dex bonus 1 + armour 4
    assert derived["weapon_damage"] == 15  # base 5 + 8 enchant + 2 str bonus
    assert derived["weapon"]["base_damage"] == 13

    listed = state.list_at(2000, 1, -2)
    assert [m["id"] for m in listed] == ["ghoul#1"]


def test_wielded_invalid_defaults_to_first_item(tmp_path, monkeypatch):
    catalog = {
        "club": {"item_id": "club", "base_power": 3, "weight": 25},
        "cloak": {"item_id": "cloak", "armour": True, "armour_class": 1, "weight": 10},
    }
    monkeypatch.setattr(monsters_state.items_catalog, "load_catalog", lambda: catalog)

    payload = {
        "monsters": [
            {
                "id": "bandit#1",
                "stats": {"str": 14, "dex": 7},
                "hp": {"current": 9, "max": 12},
                "bag": [
                    {"item_id": "club", "enchant_level": 0},
                    {"item_id": "cloak", "enchant_level": 0},
                ],
                "armour_slot": None,
                "wielded": "missing",
                "pinned_years": [1999, "1999", 2005],
                "pos": [1999, 4, 8],
            }
        ]
    }

    path = tmp_path / "instances.json"
    _write_state(path, payload)

    state = monsters_state.load_state(path)
    monster = state.list_all()[0]

    bag = monster["bag"]
    assert len(bag) == 2
    assert monster["wielded"] == bag[0]["iid"]
    assert monster["pinned_years"] == [1999, 2005]
    assert monster["derived"]["weapon_damage"] == bag[0]["derived"]["base_damage"] + 1  # str bonus 1


def test_kill_monster_drops_items_and_clears_record(tmp_path):
    catalog = {
        "club": {"item_id": "club", "base_power": 5, "weight": 20},
        "leather": {"item_id": "leather", "armour": True, "armour_class": 3, "weight": 15},
    }

    raw = {
        "id": "ogre#1",
        "name": "Ogre",
        "stats": {"str": 30, "dex": 24},
        "hp": {"current": 10, "max": 10},
        "bag": [
            {"item_id": "club", "iid": "ogre#club", "enchant_level": 15, "condition": 42},
        ],
        "armour_slot": {"item_id": "leather", "iid": "ogre#leather", "enchant_level": 2, "condition": 55},
        "wielded": "ogre#club",
        "pos": [1999, 2, 3],
    }

    normalized = monsters_state.normalize_records([raw], catalog=catalog)
    state = monsters_state.MonstersState(tmp_path / "instances.json", normalized)

    monster = state.get("ogre#1")
    assert monster is not None
    weapon = monster["bag"][0]
    armour = monster["armour_slot"]
    weapon["condition"] = 17
    armour["condition"] = 12

    summary = state.kill_monster("ogre#1")

    assert summary["monster"]["id"] == "ogre#1"
    assert summary["drops"] == [weapon, armour]
    assert summary["pos"] == [1999, 2, 3]
    assert summary["monster"]["bag"] == []
    assert summary["monster"]["armour_slot"] is None
    assert summary["monster"]["wielded"] is None
    assert summary["monster"]["hp"]["current"] == 0
    assert summary["monster"]["derived"]["armour_class"] == summary["monster"]["derived"]["dex_bonus"]
    assert weapon["condition"] == 17
    assert armour["condition"] == 12
    assert state.get("ogre#1") is None
    assert not state.list_all()


def test_kill_monster_missing_returns_empty(tmp_path):
    state = monsters_state.MonstersState(tmp_path / "instances.json", [])
    assert state.kill_monster("missing") == {"monster": None, "drops": [], "pos": None}

