"""Ensure character classes maintain independent state."""

from src.game.classes import Mage, Priest, Thief, Warrior, Wizard


def test_independence() -> None:
    a = Thief("Nix")
    b = Priest("Vera")
    c = Wizard("Orrin")
    d = Warrior("Brak")
    e = Mage("Sera")

    a.add_item("lockpick")
    a.riblets = 111
    a.ions = 7
    a.add_xp(10)

    b.add_item("rosary")
    b.riblets = 222
    b.ions = 9
    b.add_xp(20)

    assert a.inventory == ["lockpick"]
    assert b.inventory == ["rosary"]

    assert a.riblets == 111
    assert b.riblets == 222

    assert a.ions == 7
    assert b.ions == 9

    assert c.ions == 0
    assert d.riblets == 0
    assert e.inventory == []
