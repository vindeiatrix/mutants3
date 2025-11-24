import sys

sys.path.append("src")

from mutants.app import context as app_context
from mutants.services import player_state as pstate


def test_currency_setters_refresh_runtime_player(monkeypatch):
    # Avoid disk writes while exercising runtime cache updates.
    monkeypatch.setattr(pstate, "save_state", lambda data: None)

    state = {
        "active_id": "player_wizard",
        "class": "Wizard",
        "players": [
            {
                "id": "player_wizard",
                "class": "Wizard",
                "ions": 5,
                "riblets": 1,
                "exp_points": 2,
            }
        ],
        "ions_by_class": {"Wizard": 5},
        "riblets_by_class": {"Wizard": 1},
        "exp_by_class": {"Wizard": 2},
    }

    ctx = {"player_state": state}
    monkeypatch.setattr(app_context, "_CURRENT_CTX", ctx, raising=False)

    runtime_player = pstate.ensure_player_state(ctx)
    assert runtime_player["riblets"] == 1
    assert runtime_player["exp_points"] == 2

    pstate.set_riblets_for_active(state, 7)
    updated_player = pstate.ensure_player_state(ctx)
    assert updated_player["riblets"] == 7

    pstate.set_exp_for_active(state, 11)
    refreshed_player = pstate.ensure_player_state(ctx)
    assert refreshed_player["exp_points"] == 11

