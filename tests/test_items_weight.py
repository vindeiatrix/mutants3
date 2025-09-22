from mutants.services.items_weight import get_effective_weight


def test_get_effective_weight_uses_template_weight():
    inst = {"item_id": "test", "enchant_level": 0}
    template = {"weight": 30}

    assert get_effective_weight(inst, template) == 30


def test_get_effective_weight_reduces_weight_with_enchants():
    inst = {"item_id": "test", "enchant_level": 2}
    template = {"weight": 40}

    assert get_effective_weight(inst, template) == 20


def test_get_effective_weight_respects_minimum_floor():
    inst = {"item_id": "test", "enchant_level": 4}
    template = {"weight": 40}

    assert get_effective_weight(inst, template) == 10


def test_get_effective_weight_leaves_light_items_unmodified():
    inst = {"item_id": "test", "enchant_level": 3}
    template = {"weight": 8}

    assert get_effective_weight(inst, template) == 8
