import json
import sys
from pathlib import Path

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
