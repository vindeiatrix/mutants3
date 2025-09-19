"""Ensure character classes maintain independent state."""

from src.game.classes import Mage, Priest, Thief, Warrior, Wizard


def test_independence() -> None:
    a = Thief("Nix")
    b = Priest("Vera")
    c = Wizard("Orrin")
    d = Warrior("Brak")
    e = Mage("Sera")

    a.add_item("lockpick")
    a.riblets.append("shadow shard")
    a.ions["volt"] = 1
    a.add_xp(10)

    b.add_item("rosary")
    b.riblets.append("holy mote")
    b.ions["bless"] = 3
    b.add_xp(20)

    assert a.inventory == ["lockpick"]
    assert b.inventory == ["rosary"]

    assert "shadow shard" in a.riblets
    assert "shadow shard" not in b.riblets

    assert "holy mote" in b.riblets
    assert "holy mote" not in a.riblets

    assert a.ions == {"volt": 1}
    assert b.ions == {"bless": 3}

    assert c.ions == {}
    assert d.riblets == []
    assert e.inventory == []
