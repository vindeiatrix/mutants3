import json
import sys
from pathlib import Path
import pytest

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mutants.registries.items_catalog import load_catalog

SAMPLE_ITEMS = [
    {
        "item_id": "widget",
        "name": "Widget",
        "weight": 1,
        "spawnable": True,
    },
    {
        "item_id": "nonspawn",
        "name": "Nonspawn",
        "weight": 1,
        "spawnable": False,
    },
]


def test_list_spawnable(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(SAMPLE_ITEMS))
    cat = load_catalog(str(catalog_path))
    spawn_ids = {it["item_id"] for it in cat.list_spawnable()}
    assert spawn_ids == {"widget"}


def test_legacy_yes_no_coerced(tmp_path: Path) -> None:
    items = [
        {
            "item_id": "hat",
            "name": "Hat",
            "weight": 1,
            "spawnable": "yes",
            "armour": "no",
        }
    ]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(items))
    cat = load_catalog(str(catalog_path))
    hat = cat.get("hat")
    assert hat["spawnable"] is True
    assert hat["armour"] is False


def test_charges_alias_and_defaults(tmp_path: Path) -> None:
    items = [
        {
            "item_id": "rod",
            "name": "Rod",
            "weight": 1,
            "ranged": True,
            "base_power": 4,
            "charges_start": 5,
        }
    ]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(items))
    cat = load_catalog(str(catalog_path))
    rod = cat.get("rod")
    assert rod["charges_max"] == 5
    assert rod["uses_charges"] is True
    assert rod["spawnable"] is False


def test_invalid_charges_error(tmp_path: Path) -> None:
    items = [
        {
            "item_id": "bad",
            "name": "Bad",
            "weight": 1,
            "uses_charges": True,
            "charges_max": 0,
        }
    ]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(items))
    with pytest.raises(ValueError):
        load_catalog(str(catalog_path))
