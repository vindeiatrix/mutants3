import pytest

from mutants.app import context
from mutants.commands import debug as debug_cmd


def _setup(monkeypatch):
    ctx = context.build_context()
    calls = []

    def fake_create(item_id, year, x, y, origin="debug_add"):
        calls.append(item_id)

    monkeypatch.setattr(debug_cmd.itemsreg, "create_and_save_instance", fake_create)
    monkeypatch.setattr(debug_cmd.itemsreg, "clear_position", lambda iid: None)
    monkeypatch.setattr(debug_cmd.itemsreg, "save_instances", lambda: None)
    inv = []
    monkeypatch.setattr(debug_cmd.it, "_load_player", lambda: {"inventory": inv})
    monkeypatch.setattr(debug_cmd.it, "_ensure_inventory", lambda p: None)
    monkeypatch.setattr(debug_cmd.it, "_save_player", lambda p: None)
    return ctx, calls


def _run(arg, ctx):
    debug_cmd.debug_add_cmd(arg, ctx)
    return ctx["feedback_bus"].drain()


def test_exact_catalog_id(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    events = _run("nuclear_waste", ctx)
    assert calls == ["nuclear_waste"]
    assert any("added" in ev["text"] for ev in events)


def test_prefix_match(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    _run("nuclear-w", ctx)
    assert calls == ["nuclear_waste"]


def test_display_name_match(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    _run("Nuclear-Thong", ctx)
    assert calls == ["nuclear_thong"]


def test_quoted_name_with_article(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    _run('"A Nuclear-Thong"', ctx)
    assert calls == ["nuclear_thong"]


def test_ambiguous_input_warns(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    events = _run("nuclear", ctx)
    assert calls == []
    assert any("Ambiguous item ID" in ev["text"] for ev in events)


def test_unknown_input_warns(monkeypatch):
    ctx, calls = _setup(monkeypatch)
    events = _run("junkfoo", ctx)
    assert calls == []
    assert any("Unknown item" in ev["text"] for ev in events)

