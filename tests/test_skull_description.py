import sys

sys.path.append("src")

from mutants.services import combat_loot
from mutants.ui import item_display


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
