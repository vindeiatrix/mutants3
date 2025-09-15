from __future__ import annotations

from mutants.commands import quit as quit_cmd
from mutants.repl import loop
from mutants.ui.feedback import FeedbackBus


class DummyStateManager:
    def __init__(self) -> None:
        self.saved = 0
        self.executed = []

    def save_on_exit(self) -> None:
        self.saved += 1

    def on_command_executed(self, executed) -> None:
        self.executed.append(executed)


class DummyScreenManager:
    def in_selection(self) -> bool:
        return False


def test_loop_quit_triggers_save_and_exit(monkeypatch):
    state_mgr = DummyStateManager()
    bus = FeedbackBus()
    screen_mgr = DummyScreenManager()

    ctx = {
        "feedback_bus": bus,
        "state_manager": state_mgr,
        "screen_manager": screen_mgr,
        "render_next": False,
    }

    monkeypatch.setattr(loop, "build_context", lambda: ctx)
    monkeypatch.setattr(
        loop, "register_all", lambda dispatch, ctx: quit_cmd.register(dispatch, ctx)
    )

    monkeypatch.setattr(loop, "render_frame", lambda ctx: None)

    drained_events = []

    def fake_flush(local_ctx):
        drained_events.append(local_ctx["feedback_bus"].drain())

    monkeypatch.setattr(loop, "flush_feedback", fake_flush)

    inputs = iter(["quit"])

    def fake_input(prompt: str = "") -> str:
        try:
            return next(inputs)
        except StopIteration as exc:  # pragma: no cover - defensive guard
            raise AssertionError("input called after quit") from exc

    monkeypatch.setattr("builtins.input", fake_input)

    loop.main()

    assert state_mgr.saved == 2
    assert state_mgr.executed[-1] == "quit"
    assert any(ev for batch in drained_events for ev in batch if ev["text"] == "Goodbye!")
