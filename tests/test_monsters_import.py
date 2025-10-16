import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "monsters_import.py"


@pytest.fixture(scope="module")
def monsters_import():
    spec = importlib.util.spec_from_file_location("monsters_import", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _base_entry():
    return {
        "monster_id": "test_monster",
        "name": "Test Monster",
        "stats": {"str": 10, "int": 10, "wis": 10, "dex": 10, "con": 10, "cha": 10},
        "hp_max": 10,
        "armour_class": 10,
        "level": 1,
        "spawn_years": [2000],
        "spawnable": True,
        "taunt": "boo",
        "innate_attack": {
            "name": "Scratch",
            "power_base": 1,
            "power_per_level": 1,
        },
    }


def test_normalize_monster_requires_innate_line(monsters_import):
    entry = _base_entry()
    with pytest.raises(ValueError) as exc:
        monsters_import._normalize_monster(entry)
    message = str(exc.value)
    assert "innate_attack missing: line" in message or "line must be a non-empty string" in message


def test_normalize_monster_persists_innate_line(monsters_import):
    entry = _base_entry()
    entry["innate_attack"]["line"] = " The monster lunges! "
    record = monsters_import._normalize_monster(entry)
    innate = json.loads(record["innate_attack_json"])
    assert innate["line"] == "The monster lunges!"
