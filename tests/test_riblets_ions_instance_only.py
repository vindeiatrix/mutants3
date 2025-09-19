"""Riblets/ions assignments should affect only the instance."""

from src.game.classes import Warrior, Wizard


def test_riblets_ions_are_instance_fields() -> None:
    wiz = Wizard("Merla")
    war = Warrior("Thok")

    wiz.riblets = 1212
    wiz.ions = 7

    assert wiz.riblets == 1212
    assert wiz.ions == 7

    assert war.riblets == 0
    assert war.ions == 0
