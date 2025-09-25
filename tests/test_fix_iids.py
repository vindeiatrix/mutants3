import json
from pathlib import Path

from tools import fix_iids


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_fix_iids_remints_and_updates_references(tmp_path):
    state_dir = tmp_path / "state"

    items_payload = [
        {"iid": "dup", "instance_id": "dup", "item_id": "sword", "year": -1, "x": -1, "y": -1},
        {"iid": "dup", "instance_id": "dup", "item_id": "sword", "year": 2000, "x": 0, "y": 0},
    ]
    _write(state_dir / "items" / "instances.json", items_payload)

    player_payload = {
        "bags": {"Thief": ["dup"]},
        "inventory": ["dup"],
        "equipment_by_class": {"Thief": {"armour": "dup"}},
        "wielded_by_class": {"Thief": "dup"},
        "wielded": "dup",
        "players": [
            {
                "bags": {"Thief": ["dup"]},
                "inventory": ["dup"],
                "equipment_by_class": {"Thief": {"armour": "dup"}},
            }
        ],
    }
    _write(state_dir / "playerlivestate.json", player_payload)

    monsters_payload = [
        {
            "instance_id": "monster-1",
            "inventory": [{"instance_id": "dup", "item_id": "sword"}],
            "armour_wearing": "dup",
        }
    ]
    _write(state_dir / "monsters" / "instances.json", monsters_payload)

    report = fix_iids.repair(state_dir)

    assert report["items_changed"] is True
    assert report["monsters_changed"] is True

    items_after = json.loads((state_dir / "items" / "instances.json").read_text())
    ids = {entry["iid"] for entry in items_after}
    assert len(ids) == 2 and "dup" in ids
    ids.remove("dup")
    new_id = ids.pop()
    assert new_id != "dup"

    player_after = json.loads((state_dir / "playerlivestate.json").read_text())
    assert player_after["bags"]["Thief"] == ["dup"]
    assert player_after["inventory"] == ["dup"]
    assert player_after["equipment_by_class"]["Thief"]["armour"] == "dup"
    assert player_after["wielded_by_class"]["Thief"] == "dup"
    assert player_after["wielded"] == "dup"

    monsters_after = json.loads((state_dir / "monsters" / "instances.json").read_text())
    monster_entry = monsters_after[0]
    assert monster_entry["inventory"][0]["instance_id"] == new_id
    assert monster_entry["armour_wearing"] == new_id
