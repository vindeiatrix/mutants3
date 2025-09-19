import json
import sys
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mutants.registries.monsters_catalog import load_monsters_catalog, exp_for
from mutants.registries.monsters_instances import load_monsters_instances

SAMPLE_MONSTERS = [
    {
        "monster_id": "ghoul",
        "name": "Ghoul",
        "stats": {"str": 12, "int": 6, "wis": 6, "dex": 10, "con": 10, "cha": 4},
        "hp_max": 18,
        "armour_class": 1,
        "level": 3,
        "ions_min": 50,
        "ions_max": 150,
        "riblets_min": 10,
        "riblets_max": 40,
        "exp_bonus": 0,
        "innate_attack": {
            "name": "Claws",
            "power_base": 2,
            "power_per_level": 1,
            "message": "{monster} rakes {target} with claws for {damage} damage!",
        },
        "spells": ["poison_weapon"],
        "starter_items": ["monster_bait"],
        "starter_armour": None,
        "spawn_years": [2000, 2100],
        "spawnable": True,
        "taunt": "The ghoul hisses.",
    },
    {
        "monster_id": "mud_monster",
        "name": "Mud-Monster-3482",
        "stats": {"str": 10, "int": 4, "wis": 4, "dex": 8, "con": 12, "cha": 3},
        "hp_max": 14,
        "armour_class": 1,
        "level": 2,
        "ions_min": 20,
        "ions_max": 60,
        "riblets_min": 5,
        "riblets_max": 25,
        "exp_bonus": 0,
        "innate_attack": {
            "name": "Mud Sling",
            "power_base": 1,
            "power_per_level": 1,
            "message": "{monster} throws mud at {target} for {damage} damage!",
        },
        "spells": [],
        "starter_items": [],
        "starter_armour": None,
        "spawn_years": [2000, 2050],
        "spawnable": True,
        "taunt": "Glorp.",
    },
]


def _write_catalog(tmp_path: Path) -> Path:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(SAMPLE_MONSTERS))
    return catalog_path


def test_catalog_and_exp(tmp_path: Path) -> None:
    catalog_path = _write_catalog(tmp_path)
    cat = load_monsters_catalog(str(catalog_path))
    ghoul = cat.require("ghoul")
    assert ghoul["name"] == "Ghoul"
    spawnable_ids = {m["monster_id"] for m in cat.list_spawnable(2000)}
    assert {"ghoul", "mud_monster"} <= spawnable_ids
    assert exp_for(3) == 300
    assert exp_for(3, 25) == 325


def test_instances_create_and_save(tmp_path: Path) -> None:
    catalog_path = _write_catalog(tmp_path)
    cat = load_monsters_catalog(str(catalog_path))
    base = cat.require("mud_monster")
    instances_path = tmp_path / "instances.json"
    insts = load_monsters_instances(str(instances_path))
    inst = insts.create_instance(base, pos=(2000, 0, 0))
    assert inst["hp"]["current"] == base["hp_max"]
    assert inst["hp"]["max"] == base["hp_max"]
    assert inst["armour_class"] == base["armour_class"]
    assert inst["level"] == base["level"]
    assert inst["taunt"] == base["taunt"]
    assert inst["innate_attack"]["message"] == base["innate_attack"]["message"]
    insts.save()
    saved = json.loads(instances_path.read_text())
    assert saved[0]["instance_id"] == inst["instance_id"]
