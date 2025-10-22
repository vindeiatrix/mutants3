import json
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


@pytest.fixture()
def runtime_modules(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")

    module_names = [
        "mutants.state",
        "mutants.registries.sqlite_store",
        "mutants.registries.storage",
        "mutants.registries.items_catalog",
        "mutants.registries.monsters_catalog",
        "mutants.registries.items_instances",
        "mutants.registries.monsters_instances",
        "mutants.services.monster_manual_spawn",
    ]

    modules = {
        name: importlib.import_module(name)
        for name in module_names
    }

    # Reload in dependency order so the new GAME_STATE_ROOT is honoured
    modules["mutants.state"] = importlib.reload(modules["mutants.state"])
    modules["mutants.registries.sqlite_store"] = importlib.reload(
        modules["mutants.registries.sqlite_store"]
    )
    modules["mutants.registries.storage"] = importlib.reload(
        modules["mutants.registries.storage"]
    )
    modules["mutants.registries.items_catalog"] = importlib.reload(
        modules["mutants.registries.items_catalog"]
    )
    modules["mutants.registries.monsters_catalog"] = importlib.reload(
        modules["mutants.registries.monsters_catalog"]
    )
    modules["mutants.registries.items_instances"] = importlib.reload(
        modules["mutants.registries.items_instances"]
    )
    modules["mutants.registries.monsters_instances"] = importlib.reload(
        modules["mutants.registries.monsters_instances"]
    )
    modules["mutants.services.monster_manual_spawn"] = importlib.reload(
        modules["mutants.services.monster_manual_spawn"]
    )

    modules["mutants.registries.items_catalog"]._CATALOG_CACHE = None
    modules["mutants.registries.monsters_catalog"]._CATALOG_CACHE = None

    return SimpleNamespace(
        state=modules["mutants.state"],
        sqlite_store=modules["mutants.registries.sqlite_store"],
        storage=modules["mutants.registries.storage"],
        items_catalog=modules["mutants.registries.items_catalog"],
        monsters_catalog=modules["mutants.registries.monsters_catalog"],
        items_instances=modules["mutants.registries.items_instances"],
        monsters_instances=modules["mutants.registries.monsters_instances"],
        spawn=modules["mutants.services.monster_manual_spawn"],
    )


def _seed_catalogs(mods, db_path: Path) -> None:
    manager = mods.sqlite_store.SQLiteConnectionManager(db_path)
    manager.connect()

    monsters_catalog_path = REPO_ROOT / "state" / "monsters" / "catalog.json"
    items_catalog_path = REPO_ROOT / "state" / "items" / "catalog.json"

    monsters_data = json.loads(monsters_catalog_path.read_text())
    items_data = json.loads(items_catalog_path.read_text())
    items_by_id = {item["item_id"]: item for item in items_data}

    monster_id = "junkyard_scrapper"
    monster_entry = next(m for m in monsters_data if m["monster_id"] == monster_id)

    for item_id in set(monster_entry.get("starter_items", [])) | set(
        monster_entry.get("starter_armour", [])
    ):
        payload = items_by_id[item_id]
        manager.upsert_item_catalog(item_id, json.dumps(payload))

    manager.upsert_monster_catalog(monster_id, json.dumps(monster_entry))


def test_spawned_items_off_ground(runtime_modules, monkeypatch):
    mods = runtime_modules
    db_path = Path(mods.state.STATE_ROOT) / "mutants.db"
    _seed_catalogs(mods, db_path)

    stores = mods.sqlite_store.get_stores(db_path)
    # Route registry helpers to our isolated stores
    monkeypatch.setattr(mods.storage, "get_stores", lambda: stores)

    monsters_cat = mods.monsters_catalog.load_monsters_catalog(db_path)
    items_cat = mods.items_catalog.load_catalog(db_path)

    monsters_reg = mods.monsters_instances.load_monsters_instances(
        path=db_path,
        store=stores.monsters,
        kv_store=stores.runtime_kv,
    )
    items_reg = mods.items_instances.get()

    pos = (2000, 10, 10)
    instance = mods.spawn.spawn_monster_at(
        "junkyard_scrapper", pos, monsters_cat, monsters_reg, items_cat, items_reg
    )

    assert instance is not None

    monster_iid = instance["instance_id"]
    inventory = instance.get("inventory", [])
    assert inventory

    for entry in inventory:
        iid = entry["instance_id"]
        inflated = mods.items_instances.get_instance(iid)
        assert inflated["owner"] == monster_iid
        assert inflated["owner_iid"] == monster_iid
        assert (inflated["year"], inflated["x"], inflated["y"]) == (-1, -1, -1)

    year, x, y = pos
    ground_ids = mods.items_instances.list_ids_at(year, x, y)
    minted_item_ids = {
        mods.items_instances.get_instance(entry["instance_id"])["item_id"]
        for entry in inventory
    }
    assert not set(ground_ids) & minted_item_ids


def test_room_vm_deduplicates_monsters():
    from mutants.app import context as context_mod

    class DummyWorld:
        def get_tile(self, _x, _y):
            return {"edges": {"N": {}, "S": {}, "E": {}, "W": {}}, "header_idx": 0}

    class DummyMonsters:
        def list_at(self, _year, _x, _y):
            payload = {"instance_id": "mid-1", "name": "Alpha", "hp": {"current": 5}}
            return [payload, dict(payload)]

    state = {
        "active_id": "p1",
        "players": [
            {"id": "p1", "pos": [2000, 10, 10]},
        ],
    }

    vm = context_mod.build_room_vm(
        state,
        world_loader=lambda _year: DummyWorld(),
        headers=[],
        monsters=DummyMonsters(),
        items=None,
    )

    monsters_here = vm["monsters_here"]
    assert len(monsters_here) == 1
    assert monsters_here[0]["id"] == "mid-1"
