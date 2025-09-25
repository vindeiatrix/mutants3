from mutants.app.context import build_context, flush_feedback
from mutants.repl.dispatch import Dispatch


def test_flush_feedback_prints_events(capsys):
    ctx = build_context()
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])

    def foo_cmd(arg):
        ctx["feedback_bus"].push("SYSTEM/OK", "foo ran")
    dispatch.register("foo", foo_cmd)

    dispatch.call("foo", "")
    flush_feedback(ctx)
    out = capsys.readouterr().out
    assert "foo ran" in out
