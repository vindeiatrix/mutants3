import types


def _fake_catalog(monkeypatch, items):
    from mutants.registries import items as reg

    def _fake_load_raw():
        return {"items": items}

    monkeypatch.setattr(reg, "_load_raw", _fake_load_raw)
    # Force cache rebuild each test
    monkeypatch.setattr(reg, "_CACHE", {}, raising=False)
    monkeypatch.setattr(reg, "_CACHE_MTIME", None, raising=False)


def test_reject_unknown_item(monkeypatch):
    _fake_catalog(monkeypatch, [{"id": "nuclear-waste", "name": "Nuclear-Waste"}])

    # Build a minimal bus and command context
    bus = types.SimpleNamespace(msgs=[])
    bus.push = lambda ch, m: bus.msgs.append((ch, m))

    from mutants.commands import additem as cmd
    cmd.handle(["add", "zzzzz"], bus)

    assert any("Unknown item" in m for _, m in bus.msgs)


def test_accept_exact_id(monkeypatch):
    _fake_catalog(monkeypatch, [{"id": "nuclear-waste", "name": "Nuclear-Waste"}])
    bus = types.SimpleNamespace(msgs=[])
    bus.push = lambda ch, m: bus.msgs.append((ch, m))
    from mutants.commands import additem as cmd

    # You may need to patch the spawn side-effect; here we assert no rejection message.
    cmd.handle(["add", "nuclear-waste", "2"], bus)
    assert not any("Unknown item" in m for _, m in bus.msgs)


def test_accept_unique_prefix(monkeypatch):
    _fake_catalog(monkeypatch, [{"id": "nuclear-waste", "name": "Nuclear-Waste"}])
    bus = types.SimpleNamespace(msgs=[])
    bus.push = lambda ch, m: bus.msgs.append((ch, m))
    from mutants.commands import additem as cmd

    cmd.handle(["add", "nuclear"], bus)
    assert not any("Unknown item" in m for _, m in bus.msgs)
