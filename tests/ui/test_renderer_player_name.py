from __future__ import annotations

from mutants.services import player_state
from mutants.ui import renderer, styles as st


def _base_vm() -> dict:
    return {
        "header": "Test Room",
        "coords": {"x": 0, "y": 0},
        "dirs": {},
        "monsters_here": [],
        "ground_item_ids": [],
        "events": [],
        "shadows": [],
        "flags": {"dark": False},
    }


def test_render_token_lines_injects_default_player_name(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_resolve(event):
        captured["event"] = event
        return "ok"

    monkeypatch.setattr(renderer, "resolve_feedback_text", fake_resolve)
    context_payload = {"player_state": {"players": [], "active_id": None}}
    monkeypatch.setattr(renderer.appctx, "current_context", lambda: context_payload)

    vm = _base_vm()
    events = [{"kind": "SYSTEM/OK", "text": ""}]

    lines = renderer.render_token_lines(vm, feedback_events=events)

    assert captured["event"]["player_name"] == player_state.DEFAULT_PLAYER_DISPLAY_NAME
    assert captured["event"]["player"] == player_state.DEFAULT_PLAYER_DISPLAY_NAME
    assert lines[-1] == [(st.FEED_SYS_OK, "ok")]
