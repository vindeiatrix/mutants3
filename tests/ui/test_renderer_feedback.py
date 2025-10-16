from __future__ import annotations

from mutants.ui import renderer, styles as st


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
    message = "You restore 12 hit points (1,200 ions)."
    events = [{"kind": "COMBAT/HEAL", "text": message}]

    lines = renderer.render_token_lines(vm, feedback_events=events)

    assert lines[-1] == [(st.FEED_COMBAT, message)]
