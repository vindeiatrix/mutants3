from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import mutants.state as state


def _reload_state() -> ModuleType:
    return importlib.reload(state)


def test_default_state_root_matches_repo(monkeypatch):
    monkeypatch.delenv("GAME_STATE_ROOT", raising=False)
    module = _reload_state()
    expected = Path(__file__).resolve().parents[1] / "state"
    assert module.default_repo_state() == expected
    assert module.STATE_ROOT == expected
    assert module.state_path("players").parent == expected


def test_state_root_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    module = _reload_state()
    try:
        assert module.STATE_ROOT == tmp_path
        expected_file = module.state_path("foo.json")
        assert expected_file.parent == tmp_path
    finally:
        monkeypatch.delenv("GAME_STATE_ROOT", raising=False)
        _reload_state()
