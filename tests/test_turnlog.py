import logging

import pytest

from mutants.debug import turnlog
from mutants.services import player_state as pstate


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    def handle(self, event: dict[str, str]) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _reset_playersdbg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pstate, "_pdbg_setup_file_logging", lambda: None)
    yield


def test_turn_observer_logs_summary(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(pstate, "_pdbg_enabled", lambda: True)
    hp_block = {"current": 30, "max": 30}
    state = {"hp": hp_block}
    monkeypatch.setattr(pstate, "load_state", lambda: state)
    monkeypatch.setattr(pstate, "get_hp_for_active", lambda s: hp_block)

    observer = turnlog.TurnObserver()
    ctx = {"turn_observer": observer}
    observer.begin_turn(ctx, "hit", "strike")
    observer.record(
        "COMBAT/STRIKE",
        {"target_name": "Ogre", "damage": 5, "remaining_hp": 0, "killed": True},
    )
    hp_block["current"] = 25
    observer.record("COMBAT/KILL", {"victim": "ogre#1", "drops": 2, "source": "player"})

    with caplog.at_level(logging.INFO, logger="mutants.playersdbg"):
        observer.finish_turn(ctx, "hit", "strike")

    messages = [record.message for record in caplog.records if "[playersdbg] TURN" in record.message]
    assert messages, "expected playersdbg summary"
    summary = messages[-1]
    assert "HPΔ=-5" in summary
    assert "strike Ogre dmg=5" in summary
    assert "kill ogre#1 drops=2" in summary


def test_turnlog_emit_records_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pstate, "_pdbg_enabled", lambda: True)
    hp_block = {"current": 10, "max": 10}
    state = {"hp": hp_block}
    monkeypatch.setattr(pstate, "load_state", lambda: state)
    monkeypatch.setattr(pstate, "get_hp_for_active", lambda s: hp_block)

    sink = _Sink()
    observer = turnlog.TurnObserver()
    ctx = {"logsink": sink, "turn_observer": observer}

    observer.begin_turn(ctx, "strike", "strike")
    turnlog.emit(ctx, "COMBAT/STRIKE", damage=3, target="ogre")
    hp_block["current"] = 9
    observer.finish_turn(ctx, "strike", "strike")

    assert sink.events and sink.events[-1]["kind"] == "COMBAT/STRIKE"


def test_turn_observer_disabled(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(pstate, "_pdbg_enabled", lambda: False)
    observer = turnlog.TurnObserver()
    ctx = {"turn_observer": observer}
    observer.begin_turn(ctx, "hit", "strike")
    observer.record("COMBAT/STRIKE", {"damage": 3})
    with caplog.at_level(logging.INFO, logger="mutants.playersdbg"):
        observer.finish_turn(ctx, "hit", "strike")
    assert not [record for record in caplog.records if "[playersdbg] TURN" in record.message]
