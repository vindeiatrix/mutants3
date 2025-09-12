import logging

from mutants.commands.logs import _probe_wrap


def test_probe_wrap_logs_ok(caplog):
    caplog.set_level(logging.INFO)
    _probe_wrap(count=20, width=40)
    msgs = [record.getMessage() for record in caplog.records]
    assert any("UI/WRAP/OK" in m for m in msgs)
    assert not any("UI/WRAP/BAD_SPLIT" in m for m in msgs)
