import logging

from mutants.app import context
from mutants.commands import move as move_cmd
from mutants.engine import edge_resolver as er


def active(state):
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def test_move_blocked_emits_debug(monkeypatch, caplog):
    monkeypatch.setenv("WORLD_DEBUG", "1")
    move_cmd.WORLD_DEBUG = True
    er.WORLD_DEBUG = True
    ctx = context.build_context()
    p = active(ctx["player_state"])
    p["pos"] = [2000, 14, 0]
    caplog.set_level(logging.DEBUG)
    move_cmd.move("E", ctx)
    events = ctx["feedback_bus"].drain()
    assert any(ev["kind"] == "SYSTEM/DEBUG" and "reason=" in ev["text"] for ev in events)
    assert any(
        "[move] blocked" in record.getMessage() and "reason=" in record.getMessage()
        for record in caplog.records
        if record.name == "mutants.commands.move"
    )
    move_cmd.WORLD_DEBUG = False
    er.WORLD_DEBUG = False
