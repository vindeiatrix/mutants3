import sys

sys.path.append("src")

from mutants.services import combat_loot
from mutants.ui import item_display
from mutants.commands._util import items as item_util
from mutants.registries import sqlite_store


def test_describe_instance_skull_uses_monster_name(monkeypatch):
    skull_inst = {"item_id": "skull", "skull_monster_name": "Junkyard Scrapper"}

    monkeypatch.setattr(item_display.itemsreg, "get_instance", lambda iid: skull_inst)
    monkeypatch.setattr(item_display.items_catalog, "load_catalog", lambda: {"skull": {}})

    desc = item_display.describe_instance("iid-skull")

    assert "Junkyard Scrapper" in desc
    assert "skull of a" in desc.lower()


def test_drop_monster_loot_attaches_skull_metadata(monkeypatch):
    captured: list[dict[str, object]] = []

    def fake_drop_new_entries(entries, pos, origin="monster_drop"):
        captured.extend(entries)
        return ["iid-skull"]

    monkeypatch.setattr(combat_loot, "drop_new_entries", fake_drop_new_entries)
    monkeypatch.setattr(combat_loot.itemsreg, "list_instances_at", lambda *args: [])
    monkeypatch.setattr(combat_loot.itemsreg, "move_instance", lambda *args, **kwargs: False)
    monkeypatch.setattr(combat_loot.itemsreg, "get_instance", lambda iid: None)

    minted, vaporized = combat_loot.drop_monster_loot(
        pos=(0, 0, 0),
        bag_entries=[],
        armour_entry=None,
        monster={"monster_id": "rad_swarm_matron", "name": "Rad Swarm Matron"},
        catalog={},
    )

    assert not vaporized
    assert minted and minted[0].get("skull_monster_name") == "Rad Swarm Matron"
    assert captured and captured[0].get("skull_monster_id") == "rad_swarm_matron"


def test_drop_monster_loot_uses_display_name(monkeypatch):
    captured: list[dict[str, object]] = []

    def fake_drop_new_entries(entries, pos, origin="monster_drop"):
        captured.extend(entries)
        return ["iid-skull"]

    monkeypatch.setattr(combat_loot, "drop_new_entries", fake_drop_new_entries)
    monkeypatch.setattr(combat_loot.itemsreg, "list_instances_at", lambda *args: [])
    monkeypatch.setattr(combat_loot.itemsreg, "move_instance", lambda *args, **kwargs: False)
    monkeypatch.setattr(combat_loot.itemsreg, "get_instance", lambda iid: None)

    minted, vaporized = combat_loot.drop_monster_loot(
        pos=(0, 0, 0),
        bag_entries=[],
        armour_entry=None,
        monster={"monster_id": "junkyard_scrapper", "display_name": "Junkyard Scrapper"},
        catalog={},
    )

    assert not vaporized
    assert minted and minted[0].get("skull_monster_name") == "Junkyard Scrapper"
    assert captured and captured[0].get("skull_monster_name") == "Junkyard Scrapper"


def test_drop_monster_loot_sets_monotonic_created_times(monkeypatch):
    minted_sequence = iter(["bag-iid", "skull-iid", "armour-iid"])
    created_updates: list[tuple[str, int]] = []

    monkeypatch.setattr(combat_loot.itemsreg, "mint_instance", lambda *args, **kwargs: next(minted_sequence))
    monkeypatch.setattr(combat_loot.itemsreg, "list_instances_at", lambda *args, **kwargs: [])
    monkeypatch.setattr(combat_loot.itemsreg, "move_instance", lambda *args, **kwargs: False)
    monkeypatch.setattr(combat_loot.itemsreg, "get_instance", lambda *args, **kwargs: None)
    monkeypatch.setattr(combat_loot.itemsreg, "mint_on_ground_with_defaults", lambda *args, **kwargs: "fallback")

    def capture_created_at(iid, **fields):
        if "created_at" in fields:
            created_updates.append((iid, fields["created_at"]))
        return {"iid": iid, **fields}

    monkeypatch.setattr(combat_loot.itemsreg, "update_instance", capture_created_at)

    minted, vaporized = combat_loot.drop_monster_loot(
        pos=(0, 0, 0),
        bag_entries=[{"item_id": "bolt_pouch"}],
        armour_entry={"item_id": "torn_overalls"},
        monster={},
        catalog={},
    )

    assert not vaporized
    assert [entry["iid"] for entry in minted] == ["bag-iid", "skull-iid", "armour-iid"]
    assert [entry[0] for entry in created_updates] == ["bag-iid", "skull-iid", "armour-iid"]
    assert all(a[1] < b[1] for a, b in zip(created_updates, created_updates[1:]))


def test_drop_monster_loot_orders_skull_before_armour(monkeypatch):
    minted_sequence = iter(["bag-iid", "skull-iid", "armour-iid"])
    created_updates: list[tuple[str, int]] = []

    monkeypatch.setattr(combat_loot.itemsreg, "mint_instance", lambda *args, **kwargs: next(minted_sequence))
    monkeypatch.setattr(combat_loot.itemsreg, "list_instances_at", lambda *args, **kwargs: [])
    monkeypatch.setattr(combat_loot.itemsreg, "move_instance", lambda *args, **kwargs: False)
    monkeypatch.setattr(combat_loot.itemsreg, "get_instance", lambda *args, **kwargs: None)
    monkeypatch.setattr(combat_loot.itemsreg, "mint_on_ground_with_defaults", lambda *args, **kwargs: "fallback")

    def capture_created_at(iid, **fields):
        if "created_at" in fields:
            created_updates.append((iid, fields["created_at"]))
        return {"iid": iid, **fields}

    monkeypatch.setattr(combat_loot.itemsreg, "update_instance", capture_created_at)

    minted, vaporized = combat_loot.drop_monster_loot(
        pos=(0, 0, 0),
        bag_entries=[
            {"item_id": "rusty_shiv", "drop_source": "bag"},
            {"item_id": "torn_overalls", "drop_source": "armour", "worn": True},
        ],
        armour_entry=None,
        monster={},
        catalog={},
    )

    assert not vaporized
    assert [entry["iid"] for entry in minted] == ["bag-iid", "skull-iid", "armour-iid"]
    assert [entry[0] for entry in created_updates] == ["bag-iid", "skull-iid", "armour-iid"]
    assert all(a[1] < b[1] for a, b in zip(created_updates, created_updates[1:]))


def test_drop_new_entries_strips_unsupported_fields(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(combat_loot.itemsreg, "mint_instance", lambda *args, **kwargs: "iid-skull")
    monkeypatch.setattr(combat_loot.itemsreg, "list_instances_at", lambda *args, **kwargs: [])
    monkeypatch.setattr(combat_loot.itemsreg, "move_instance", lambda *args, **kwargs: False)
    monkeypatch.setattr(combat_loot.itemsreg, "get_instance", lambda iid: None)
    monkeypatch.setattr(combat_loot.itemsreg, "mint_on_ground_with_defaults", lambda *args, **kwargs: "iid-skull")

    def capture_update(_iid, **fields):
        captured.update(fields)
        return {"iid": _iid}

    monkeypatch.setattr(combat_loot.itemsreg, "update_instance", capture_update)

    monster = {"monster_id": "junkyard_scrapper", "name": "Junkyard Scrapper-777"}
    entry = {"item_id": "skull", "enchant_level": 1, "notes": "ignored", "tags": ["a-tag"]}
    entry.update(combat_loot._skull_metadata(monster))

    combat_loot.drop_new_entries([entry], (0, 0, 0))

    assert captured.get("skull_monster_name") == "Junkyard Scrapper-777"
    assert captured.get("skull_monster_id") == "junkyard_scrapper"
    assert "enchanted" not in captured
    assert "notes" not in captured
    assert "tags" not in captured


def test_resolve_item_arg_matches_skull_without_catalog(monkeypatch):
    monkeypatch.setattr(
        item_util, "inventory_iids_for_active_player", lambda ctx: ["iid-skull"]
    )

    class DummyCatalog:
        @staticmethod
        def get(item_id):
            return None

    monkeypatch.setattr(item_util.items_catalog, "load_catalog", lambda: DummyCatalog())
    monkeypatch.setattr(
        item_util.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": "skull"}
    )

    resolved = item_util.resolve_item_arg({}, "sku")

    assert resolved == "iid-skull"


def test_resolve_item_arg_survives_catalog_errors(monkeypatch):
    monkeypatch.setattr(
        item_util, "inventory_iids_for_active_player", lambda ctx: ["iid-skull"]
    )

    def blow_up():
        raise FileNotFoundError("missing catalog")

    monkeypatch.setattr(item_util.items_catalog, "load_catalog", blow_up)
    monkeypatch.setattr(
        item_util.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": "skull"}
    )

    resolved = item_util.resolve_item_arg({}, "sk")

    assert resolved == "iid-skull"


def test_describe_instance_skull_uses_monster_id(monkeypatch):
    skull_inst = {"item_id": "skull", "skull_monster_id": "ashen_hulk"}

    monkeypatch.setattr(item_display.itemsreg, "get_instance", lambda iid: skull_inst)
    monkeypatch.setattr(item_display.items_catalog, "load_catalog", lambda: {"skull": {}})

    desc = item_display.describe_instance("iid-skull")

    assert "Ashen Hulk" in desc


def test_describe_instance_skull_uses_correct_article(monkeypatch):
    skull_inst = {"item_id": "skull", "skull_monster_name": "Elder Fiend"}

    monkeypatch.setattr(item_display.itemsreg, "get_instance", lambda iid: skull_inst)
    monkeypatch.setattr(item_display.items_catalog, "load_catalog", lambda: {"skull": {}})

    desc = item_display.describe_instance("iid-skull")

    assert "skull of an Elder Fiend" in desc


def test_sqlite_store_persists_skull_metadata(tmp_path):
    db_path = tmp_path / "mutants.db"
    manager = sqlite_store.SQLiteConnectionManager(db_path)
    store = sqlite_store.SQLiteItemsInstanceStore(manager)

    store.mint({"iid": "iid-1", "item_id": "skull", "year": 0, "x": 0, "y": 0, "created_at": 0})
    store.update_fields(
        "iid-1", skull_monster_id="junkyard_scrapper", skull_monster_name="Junkyard Scrapper"
    )

    record = store.get_by_iid("iid-1")

    assert record["skull_monster_id"] == "junkyard_scrapper"
    assert record["skull_monster_name"] == "Junkyard Scrapper"
