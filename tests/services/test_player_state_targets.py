from __future__ import annotations

from pathlib import Path

import pytest

from mutants import env, state
from mutants.bootstrap import lazyinit
from mutants.services import player_state


@pytest.fixture
def configure_state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(state, "STATE_ROOT", tmp_path)
    env._CONFIG_LOGGED = False  # reset cached log state between tests
    return tmp_path


def test_ready_target_round_trip(configure_state_root: Path) -> None:
    lazyinit.ensure_player_state(
        state_dir=str(configure_state_root),
        out_name="playerlivestate.json",
    )

    initial = player_state.load_state()
    klass = player_state.get_active_class(initial)

    assert klass in initial["ready_target_by_class"]
    assert klass in initial["target_monster_id_by_class"]
    assert initial["ready_target_by_class"][klass] is None
    assert initial["target_monster_id_by_class"][klass] is None

    active = initial.get("active", {})
    assert active.get("ready_target") is None
    assert active.get("target_monster_id") is None
    assert active.get("target_monster_id_by_class", {}).get(klass) is None

    monster_id = "monster-alpha"
    player_state.set_ready_target_for_active(monster_id)

    updated = player_state.load_state()
    klass = player_state.get_active_class(updated)
    assert updated["ready_target_by_class"][klass] == monster_id
    assert updated["target_monster_id_by_class"][klass] == monster_id

    active = updated.get("active", {})
    assert active.get("ready_target") == monster_id
    assert active.get("target_monster_id") == monster_id
    assert active.get("target_monster_id_by_class", {}).get(klass) == monster_id

    players = updated.get("players", [])
    for player in players:
        if player.get("id") == updated.get("active_id"):
            assert player.get("target_monster_id_by_class", {}).get(klass) == monster_id
            break
    else:  # pragma: no cover - defensive guard should not trigger
        pytest.fail("active player not found in state")

    player_state.clear_ready_target_for_active(reason="round-trip-test")

    cleared = player_state.load_state()
    klass = player_state.get_active_class(cleared)
    assert cleared["ready_target_by_class"][klass] is None
    assert cleared["target_monster_id_by_class"][klass] is None

    active = cleared.get("active", {})
    assert active.get("ready_target") is None
    assert active.get("target_monster_id") is None
    assert active.get("target_monster_id_by_class", {}).get(klass) is None

    players = cleared.get("players", [])
    for player in players:
        if player.get("id") == cleared.get("active_id"):
            assert player.get("target_monster_id_by_class", {}).get(klass) is None
            break
    else:  # pragma: no cover - defensive guard should not trigger
        pytest.fail("active player not found in state after clear")
