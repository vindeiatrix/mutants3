import pytest

from mutants.app import context
from mutants.app.context import render_frame
from mutants.commands.move import move
from mutants.commands.look import look_cmd
from mutants.data.room_headers import ROOM_HEADERS


def active(state):
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def make_ctx():
    ctx = context.build_context()
    screen = ctx.get("screen_manager")
    if screen:
        screen.enter_game(ctx)
        ctx["render_next"] = False
    return ctx


def test_look_renders_room(capsys):
    ctx = make_ctx()
    look_cmd("", ctx)
    render_frame(ctx)
    out = capsys.readouterr().out
    assert ROOM_HEADERS[3] in out


def test_move_north_updates_position_and_feedback():
    ctx = make_ctx()
    p = active(ctx["player_state"])
    p["pos"] = [2000, 0, 0]
    move("N", ctx)
    assert p["pos"] == [2000, 0, 1]
    events = ctx["feedback_bus"].drain()
    # No movement echo; success should not emit MOVE/OK.
    assert not any(ev["kind"] == "MOVE/OK" for ev in events)


def test_boundary_blocks_movement():
    ctx = make_ctx()
    p = active(ctx["player_state"])
    p["pos"] = [2000, 14, 0]
    move("E", ctx)
    assert p["pos"] == [2000, 14, 0]
    events = ctx["feedback_bus"].drain()
    assert any(ev["kind"] == "MOVE/BLOCKED" and ev["text"] == "You're blocked!" for ev in events)


def test_peek_direction_renders_adjacent_room(capsys):
    ctx = make_ctx()
    p = active(ctx["player_state"])
    p["pos"] = [2000, 0, 0]
    look_cmd("north", ctx)
    assert ctx["render_next"]
    render_frame(ctx)
    out = capsys.readouterr().out
    assert ROOM_HEADERS[11] in out
    assert p["pos"] == [2000, 0, 0]


def test_peek_direction_prefix_renders_adjacent_room(capsys):
    ctx = make_ctx()
    p = active(ctx["player_state"])
    p["pos"] = [2000, 0, 0]
    look_cmd("we", ctx)
    assert ctx["render_next"]
    render_frame(ctx)
    out = capsys.readouterr().out
    assert ROOM_HEADERS[7] in out
    assert p["pos"] == [2000, 0, 0]


def test_peek_blocked_does_not_render():
    ctx = make_ctx()
    p = active(ctx["player_state"])
    p["pos"] = [2000, 14, 0]
    look_cmd("east", ctx)
    assert not ctx["render_next"]
    events = ctx["feedback_bus"].drain()
    assert any(ev["kind"] == "LOOK/BLOCKED" for ev in events)
