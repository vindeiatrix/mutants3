from mutants.commands.logs import _probe_wrap
from mutants.app import context


def test_probe_wrap_logs_ok():
    ctx = context.build_context()
    bus = ctx["feedback_bus"]
    bus.drain()
    _probe_wrap(count=20, width=40, ctx=ctx)
    events = bus.drain()
    texts = [e["text"] for e in events]
    assert any("UI/WRAP/OK" in t for t in texts)
    assert not any("UI/WRAP/BAD_SPLIT" in t for t in texts)
