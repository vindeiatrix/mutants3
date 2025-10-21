from mutants.services import player_state


def test_get_player_display_name_prefers_active_name() -> None:
    state = {"players": [{"id": "p1", "name": "Vindy"}], "active_id": "p1"}

    assert player_state.get_player_display_name(state) == "Vindy"


def test_get_player_display_name_defaults_when_missing() -> None:
    state = {"players": [{"id": "p1"}], "active_id": "p1"}

    assert (
        player_state.get_player_display_name(state)
        == player_state.DEFAULT_PLAYER_DISPLAY_NAME
    )
