from __future__ import annotations

from mutants.ui import renderer, styles as st, textutils


def _base_vm() -> dict:
    return {
        "header": "Test",
        "coords": {"x": 0, "y": 0},
        "dirs": {},
        "monsters_here": [],
        "ground_item_ids": [],
        "events": [],
        "shadows": [],
        "flags": {"dark": False},
    }


def test_feedback_heal_message_rendering() -> None:
    vm = _base_vm()
    events = [
        {
            "kind": "COMBAT/HEAL",
            "template": textutils.TEMPLATE_MONSTER_HEAL,
            "monster": "Goblin",
            "hp": 12,
            "ions": 1200,
        }
    ]

    lines = renderer.render_token_lines(vm, feedback_events=events)

    expected_message = textutils.render_feedback_template(
        textutils.TEMPLATE_MONSTER_HEAL,
        monster="Goblin",
        hp=12,
        ions=1200,
    )

    assert lines[-1] == [(st.FEED_COMBAT, expected_message)]


def test_feedback_monster_heal_visual_message_rendering() -> None:
    vm = _base_vm()
    events = [
        {
            "kind": "COMBAT/HEAL_MONSTER",
            "template": textutils.TEMPLATE_MONSTER_HEAL_VISUAL,
            "monster": "Ghoul",
        }
    ]

    lines = renderer.render_token_lines(vm, feedback_events=events)

    expected_message = textutils.render_feedback_template(
        textutils.TEMPLATE_MONSTER_HEAL_VISUAL,
        monster="Ghoul",
    )

    assert lines[-1] == [(st.FEED_COMBAT, expected_message)]
