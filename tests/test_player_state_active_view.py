import sys

sys.path.append("src")

from mutants.services import player_state as pstate


def test_active_view_uses_canonical_currencies():
    state = {
        "active_id": "player_wizard",
        "class": "Wizard",
        "players": [
            {
                "id": "player_wizard",
                "class": "Wizard",
                "ions": 0,
                "riblets": 0,
                "exp_points": 0,
            }
        ],
        "ions_by_class": {"Wizard": 5},
        "riblets_by_class": {"Wizard": 3},
        "exp_by_class": {"Wizard": 9},
    }

    view = pstate.build_active_view(state)

    assert view["ions"] == 5
    assert view["riblets"] == 3
    assert view["exp_points"] == 9
