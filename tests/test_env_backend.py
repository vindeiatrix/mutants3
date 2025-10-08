from __future__ import annotations

import importlib
import logging
from types import ModuleType

import mutants.env as env
import mutants.state as state


def _reload_state() -> ModuleType:
    return importlib.reload(state)


def _reload_env() -> ModuleType:
    return importlib.reload(env)


def test_backend_defaults_to_json_and_logs(monkeypatch, caplog) -> None:
    monkeypatch.delenv("MUTANTS_STATE_BACKEND", raising=False)
    monkeypatch.delenv("GAME_STATE_ROOT", raising=False)
    state_module = _reload_state()
    env_module = _reload_env()

    try:
        with caplog.at_level(logging.INFO, logger="mutants.env"):
            caplog.clear()
            backend = env_module.get_state_backend()
            env_module.get_state_backend()

        assert backend == "json"
        assert len(caplog.records) == 1
        message = caplog.records[0].message
        expected_path = env_module.get_state_database_path()
        assert expected_path == state_module.state_path("mutants.db")
        assert f"backend={backend}" in message
        assert str(expected_path) in message
    finally:
        monkeypatch.delenv("MUTANTS_STATE_BACKEND", raising=False)
        monkeypatch.delenv("GAME_STATE_ROOT", raising=False)
        _reload_state()
        _reload_env()


def test_backend_switches_to_sqlite(monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    state_module = _reload_state()
    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    env_module = _reload_env()

    try:
        with caplog.at_level(logging.INFO, logger="mutants.env"):
            caplog.clear()
            backend = env_module.get_state_backend()

        assert backend == "sqlite"
        path = env_module.get_state_database_path()
        assert path == state_module.state_path("mutants.db")
        assert path.parent == tmp_path
        assert len(caplog.records) == 1
        message = caplog.records[0].message
        assert "backend=sqlite" in message
        assert str(path) in message
    finally:
        monkeypatch.delenv("MUTANTS_STATE_BACKEND", raising=False)
        monkeypatch.delenv("GAME_STATE_ROOT", raising=False)
        _reload_state()
        _reload_env()
