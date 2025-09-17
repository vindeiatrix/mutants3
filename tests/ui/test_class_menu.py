import pytest

from mutants.app import context
from mutants.ui.class_menu import handle_input, render_menu


def make_ctx():
    ctx = context.build_context()
    ctx["feedback_bus"].drain()
    return ctx


def test_render_menu_mentions_exit_instruction():
    ctx = make_ctx()
    render_menu(ctx)
    events = ctx["feedback_bus"].drain()
    assert any(
        ev["kind"] == "SYSTEM/OK"
        and "Type BURY [class number] to reset a player. Type X to exit." in ev["text"]
        for ev in events
    )


def test_handle_input_x_exits_cleanly():
    ctx = make_ctx()
    with pytest.raises(SystemExit) as excinfo:
        handle_input("x", ctx)
    assert excinfo.value.code == 0
