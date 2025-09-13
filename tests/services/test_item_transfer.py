import types

from mutants.services import item_transfer
from mutants.registries import items_instances as itemsreg


def mk_ctx():
    return {
        "player_state": {
            "active_id": 1,
            "players": [{"id": 1, "pos": [2000, 0, 0]}],
        },
        "world_loader": lambda year: None,
    }


def patch_items(monkeypatch, player):
    monkeypatch.setattr(item_transfer, "_load_player", lambda: player)
    monkeypatch.setattr(item_transfer, "_save_player", lambda p: None)
    monkeypatch.setattr(itemsreg, "set_position", lambda iid, yr, x, y: None)
    monkeypatch.setattr(itemsreg, "clear_position", lambda iid: None)
    monkeypatch.setattr(itemsreg, "list_instances_at", lambda yr, x, y: [])
    monkeypatch.setattr(itemsreg, "save_instances", lambda: None)
    monkeypatch.setattr(itemsreg, "get_instance", lambda iid: None)


def test_armor_iid_armour():
    player = {"armour": "helmet"}
    assert item_transfer._armor_iid(player) == "helmet"


def test_drop_blocked_for_armor(monkeypatch):
    player = {"inventory": ["helm"], "armor": {"iid": "helm"}}
    patch_items(monkeypatch, player)
    ctx = mk_ctx()
    res = item_transfer.drop_to_ground(ctx, "")
    assert res["ok"] is False
    assert res["reason"] == "armor_cannot_drop"
    assert player["inventory"] == ["helm"]


def test_drop_blocked_for_armour(monkeypatch):
    player = {"inventory": ["helm"], "armour": {"iid": "helm"}}
    patch_items(monkeypatch, player)
    ctx = mk_ctx()
    res = item_transfer.drop_to_ground(ctx, "")
    assert res["ok"] is False
    assert res["reason"] == "armor_cannot_drop"
    assert player["inventory"] == ["helm"]
