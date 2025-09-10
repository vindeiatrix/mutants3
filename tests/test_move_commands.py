import pytest

from mutants.bootstrap.lazyinit import ensure_player_state
from mutants.commands.move import register
from mutants.data.room_headers import ROOM_HEADERS
from mutants.registries.world import load_year
from mutants.ui.renderer import render
from mutants.__main__ import active


def make_ctx():
    state = ensure_player_state()
    ctx = {
        "player_state": state,
        "world_loader": load_year,
        "monsters": None,
        "items": None,
        "headers": ROOM_HEADERS,
        "render": lambda vm: render(vm),
    }
    dispatch = {}
    register(dispatch, ctx)
    return ctx, dispatch, state


def test_look_renders_room(capsys):
    ctx, dispatch, state = make_ctx()
    dispatch["look"]("")
    out = capsys.readouterr().out
    assert "Graffiti lines the city walls." in out


def test_move_north_updates_position_and_renders(capsys):
    ctx, dispatch, state = make_ctx()
    p = active(state)
    p["pos"] = [2000, 0, 0]
    dispatch["north"]("")
    out = capsys.readouterr().out
    assert p["pos"] == [2000, 0, 1]
    assert "You're in an abandoned building." in out


def test_boundary_blocks_movement(capsys):
    ctx, dispatch, state = make_ctx()
    p = active(state)
    p["pos"] = [2000, 14, 0]
    dispatch["east"]("")
    out = capsys.readouterr().out
    assert p["pos"] == [2000, 14, 0]
    assert "A boundary blocks your way." in out
