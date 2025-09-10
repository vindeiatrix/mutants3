import pytest

from mutants.app import context
from mutants.app.context import render_frame
from mutants.commands.move import move
from mutants.commands.look import look_cmd


def active(state):
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def make_ctx():
    return context.build_context()


def test_look_renders_room(capsys):
    ctx = make_ctx()
    look_cmd("", ctx)
    render_frame(ctx)
    out = capsys.readouterr().out
    assert "Graffiti lines the city walls." in out


def test_move_north_updates_position_and_feedback():
    ctx = make_ctx()
    p = active(ctx["player_state"])
    p["pos"] = [2000, 0, 0]
    move("N", ctx)
    assert p["pos"] == [2000, 0, 1]
    events = ctx["feedback_bus"].drain()
    assert any(ev["kind"] == "MOVE/OK" for ev in events)


def test_boundary_blocks_movement():
    ctx = make_ctx()
    p = active(ctx["player_state"])
    p["pos"] = [2000, 14, 0]
    move("E", ctx)
    assert p["pos"] == [2000, 14, 0]
    events = ctx["feedback_bus"].drain()
    assert any(ev["kind"] == "MOVE/BLOCKED" for ev in events)
