import pytest

from mutants.app import context
from mutants.commands import debug as debug_cmd


def _setup(monkeypatch):
    ctx = context.build_context()
    calls = []

    def fake_create(item_id, year, x, y, origin="debug_add"):
        calls.append(item_id)

    monkeypatch.setattr(debug_cmd.itemsreg, "create_and_save_instance", fake_create)
    return ctx, calls


def _run(cmd, ctx):
    debug_cmd.debug_cmd(cmd, ctx)
    return ctx["feedback_bus"].drain()


def test_exact_catalog_id(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    events = _run("add item nuclear_waste", ctx)
    assert calls == ["nuclear_waste"]
    assert any("added" in ev["text"] for ev in events)


def test_prefix_match(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    _run("add item nuclear-w", ctx)
    assert calls == ["nuclear_waste"]


def test_display_name_match(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    _run("add item Nuclear-Thong", ctx)
    assert calls == ["nuclear_thong"]


def test_quoted_name_with_article(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    _run('add item "A Nuclear-Thong"', ctx)
    assert calls == ["nuclear_thong"]


def test_ambiguous_input_warns(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    events = _run("add item nuclear", ctx)
    assert calls == []
    assert any("Ambiguous item ID" in ev["text"] for ev in events)


def test_unknown_input_warns(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    events = _run("add item junkfoo", ctx)
    assert calls == []
    assert any("Unknown item" in ev["text"] for ev in events)

