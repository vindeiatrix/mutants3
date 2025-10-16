from mutants.services.monster_entities import (
    DEFAULT_INNATE_ATTACK_LINE,
    MonsterInstance,
    MonsterTemplate,
)


def test_template_innate_attack_line_uses_catalog_value():
    template = MonsterTemplate(
        monster_id="alpha",
        name="Alpha",
        level=1,
        hp_max=5,
        armour_class=10,
        spawn_years=[2000],
        spawnable=True,
        taunt="boo",
        stats={},
        innate_attack={"name": "Swipe", "line": "{monster} swipes {target}!"},
        exp_bonus=None,
        ions_min=None,
        ions_max=None,
        riblets_min=None,
        riblets_max=None,
        spells=(),
        starter_armour=(),
        starter_items=(),
    )
    assert template.innate_attack_line == "{monster} swipes {target}!"


def test_template_innate_attack_line_falls_back():
    template = MonsterTemplate(
        monster_id="beta",
        name="Beta",
        level=1,
        hp_max=5,
        armour_class=10,
        spawn_years=[2000],
        spawnable=True,
        taunt="",
        stats={},
        innate_attack={"name": "Bop"},
        exp_bonus=None,
        ions_min=None,
        ions_max=None,
        riblets_min=None,
        riblets_max=None,
        spells=(),
        starter_armour=(),
        starter_items=(),
    )
    assert template.innate_attack_line == DEFAULT_INNATE_ATTACK_LINE


def test_instance_innate_attack_line_prefers_instance_payload():
    template = MonsterTemplate(
        monster_id="gamma",
        name="Gamma",
        level=1,
        hp_max=5,
        armour_class=10,
        spawn_years=[2000],
        spawnable=True,
        taunt="",
        stats={},
        innate_attack={"name": "Scratch", "line": "{monster} scratches {target}!"},
        exp_bonus=None,
        ions_min=None,
        ions_max=None,
        riblets_min=None,
        riblets_max=None,
        spells=(),
        starter_armour=(),
        starter_items=(),
    )
    instance = MonsterInstance(
        instance_id="inst",
        monster_id="gamma",
        name="Gamma",
        innate_attack={"name": "Scratch", "line": "{monster} mauls {target}!"},
        template=template,
    )
    assert instance.innate_attack_line == "{monster} mauls {target}!"


def test_instance_innate_attack_line_uses_template_fallback():
    template = MonsterTemplate(
        monster_id="delta",
        name="Delta",
        level=1,
        hp_max=5,
        armour_class=10,
        spawn_years=[2000],
        spawnable=True,
        taunt="",
        stats={},
        innate_attack={"name": "Strike", "line": "{monster} strikes {target}!"},
        exp_bonus=None,
        ions_min=None,
        ions_max=None,
        riblets_min=None,
        riblets_max=None,
        spells=(),
        starter_armour=(),
        starter_items=(),
    )
    instance = MonsterInstance(
        instance_id="inst",
        monster_id="delta",
        name="Delta",
        innate_attack={},
        template=template,
    )
    assert instance.innate_attack_line == "{monster} strikes {target}!"


def test_instance_innate_attack_line_uses_default_without_template():
    instance = MonsterInstance(
        instance_id="inst",
        monster_id="epsilon",
        name="",
        innate_attack={},
        template=None,
    )
    assert instance.innate_attack_line == DEFAULT_INNATE_ATTACK_LINE
