import json
from pathlib import Path
from typing import Mapping

from mutants.registries import monsters_instances
from mutants.services import monsters_state


def test_kill_monster_drops_inventory_items(tmp_path):
    catalog_entries = json.loads(
        (Path(__file__).resolve().parent.parent / "state/monsters/catalog.json").read_text()
    )
    template = next(entry for entry in catalog_entries if entry.get("monster_id") == "rad_swarm_matron")

    monster = dict(template)
    monster.update(
        {
            "id": "rad#loot",
            "instance_id": "rad#loot",
            "pos": [0, 0, 0],
            "hp": {"current": template["hp_max"], "max": template["hp_max"]},
            "inventory": [
                {"item_id": "Brood Tags"},
                {"item_id": "Bolt Pouch"},
            ],
        }
    )

    normalized = monsters_state._normalize_monsters([monster], catalog={})
    instances = monsters_instances.load_monsters_instances(tmp_path / "monsters.json")
    state = monsters_state.MonstersState(tmp_path / "monsters.json", normalized, instances=instances)

    summary = state.kill_monster(monster["id"])

    dropped = {
        entry.get("item_id")
        for entry in summary.get("bag_drops", [])
        if isinstance(entry, Mapping)
    }

    assert dropped >= {"Brood Tags", "Bolt Pouch"}


def test_kill_monster_merges_bag_and_inventory(tmp_path):
    catalog_entries = json.loads(
        (Path(__file__).resolve().parent.parent / "state/monsters/catalog.json").read_text()
    )
    template = next(entry for entry in catalog_entries if entry.get("monster_id") == "rad_swarm_matron")

    monster = dict(template)
    monster.update(
        {
            "id": "rad#merge",
            "instance_id": "rad#merge",
            "pos": [0, 0, 0],
            "bag": [{"item_id": "Brood Tags"}],
            "inventory": [
                {"item_id": "Bolt Pouch"},
                {"item_id": "Rusty Shiv"},
            ],
            "hp": {"current": template["hp_max"], "max": template["hp_max"]},
        }
    )

    normalized = monsters_state._normalize_monsters([monster], catalog={})
    instances = monsters_instances.load_monsters_instances(tmp_path / "monsters.json")
    state = monsters_state.MonstersState(tmp_path / "monsters.json", normalized, instances=instances)

    summary = state.kill_monster(monster["id"])

    dropped = {
        entry.get("item_id")
        for entry in summary.get("bag_drops", [])
        if isinstance(entry, Mapping)
    }

    assert dropped == {"Brood Tags", "Bolt Pouch", "Rusty Shiv"}
