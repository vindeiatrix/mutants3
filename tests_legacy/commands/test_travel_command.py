from __future__ import annotations

import pytest

from mutants.commands.travel import _floor_to_century, _parse_year, travel_cmd


class DummyBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def push(self, kind: str, text: str, **_: object) -> None:
        self.events.append((kind, text))


def test_floor_to_century() -> None:
    assert _floor_to_century(2314) == 2300
    assert _floor_to_century(2100) == 2100
    assert _floor_to_century(-50) == -100


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2100", 2100),
        ("+2100", 2100),
        ("  2455ad", 2455),
        ("", None),
        ("abc", None),
    ],
)
def test_parse_year(raw: str, expected: int | None) -> None:
    assert _parse_year(raw) == expected


def make_ctx(bus: DummyBus, *, years: list[int] | None = None, loader=None) -> dict[str, object]:
    ctx: dict[str, object] = {"feedback_bus": bus, "render_next": False, "peek_vm": object()}
    if years is not None:
        ctx["world_years"] = years
    if loader is not None:
        ctx["world_loader"] = loader
    return ctx


def test_travel_requires_year() -> None:
    bus = DummyBus()
    ctx = make_ctx(bus, years=[2000, 2100])
    travel_cmd("", ctx)
    assert bus.events[-1] == (
        "SYSTEM/WARN",
        "Usage: TRAVEL <year>  (e.g., 'tra 2100').",
    )
    assert ctx["render_next"] is False


def test_travel_rejects_future_year_without_files() -> None:
    loader_called = False

    def _loader(_: int) -> None:
        nonlocal loader_called
        loader_called = True
        raise AssertionError("loader should not be called when year is unavailable")

    bus = DummyBus()
    ctx = make_ctx(bus, years=[2000, 2100], loader=_loader)

    travel_cmd("2200", ctx)

    assert loader_called is False
    assert bus.events[-1] == ("SYSTEM/WARN", "That year doesn't exist yet!")
    assert ctx["render_next"] is False


def test_travel_same_century_returns_to_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = DummyBus()
    ctx = make_ctx(bus, years=[2100, 2200], loader=lambda year: type("W", (), {"year": year})())

    player = {"id": "player_thief", "pos": [2100, 5, 6], "inventory": [], "ions": 9000}
    saved: dict[str, object] = {}

    monkeypatch.setattr("mutants.commands.travel.itx._load_player", lambda: player)
    monkeypatch.setattr("mutants.commands.travel.itx._ensure_inventory", lambda _: None)
    monkeypatch.setattr(
        "mutants.commands.travel.itx._save_player",
        lambda payload: saved.update({"player": payload.copy()}),
    )
    new_state = {"players": [player], "active_id": "player_thief"}
    monkeypatch.setattr("mutants.commands.travel.pstate.load_state", lambda: new_state)

    travel_cmd("2150", ctx)

    assert saved["player"]["pos"] == [2100, 0, 0]
    assert saved["player"]["ions"] == 9000
    assert ctx["player_state"] is new_state
    assert ctx["render_next"] is False
    assert bus.events[-1] == (
        "SYSTEM/OK",
        "You're already in the 22th Century!",
    )


def test_travel_cross_century_full_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = DummyBus()

    def _loader(year: int):
        return type("W", (), {"year": year})()

    ctx = make_ctx(bus, years=[2000, 2100, 2300], loader=_loader)
    player = {"id": "player_thief", "pos": [2100, 1, 2], "inventory": [], "ions": 7000}
    state = {
        "players": [
            {"id": "player_thief", "pos": [2100, 1, 2], "ions": 7000},
        ],
        "active_id": "player_thief",
        "active": {"id": "player_thief", "pos": [2100, 1, 2], "ions": 7000},
    }
    save_calls: list[dict[str, object]] = []

    monkeypatch.setattr("mutants.commands.travel.itx._load_player", lambda: player)
    monkeypatch.setattr("mutants.commands.travel.itx._ensure_inventory", lambda _: None)
    monkeypatch.setattr(
        "mutants.commands.travel.itx._save_player",
        lambda _: pytest.fail("_save_player should not be called for travel moves"),
    )

    def _load_state() -> dict[str, object]:
        return state

    def _save_state(payload: dict[str, object]) -> None:
        snapshot = dict(payload)
        save_calls.append(snapshot)
        state.clear()
        state.update(snapshot)

    monkeypatch.setattr("mutants.commands.travel.pstate.load_state", _load_state)
    monkeypatch.setattr("mutants.commands.travel.pstate.save_state", _save_state)

    travel_cmd("2300", ctx)

    assert player["ions"] == 1000
    assert state["players"][0]["pos"] == [2300, 0, 0]
    assert state["active"]["pos"] == [2300, 0, 0]
    assert ctx["player_state"]["players"][0]["pos"] == [2300, 0, 0]
    assert ctx["player_state"]["active"]["pos"] == [2300, 0, 0]
    assert ctx["render_next"] is False
    assert save_calls, "expected save_state to be invoked"
    assert bus.events[-1] == (
        "SYSTEM/OK",
        "ZAAAPPPPP!! You've been sent to the year 2300 A.D.",
    )


def test_travel_requires_minimum_ions(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = DummyBus()
    ctx = make_ctx(bus, years=[2000, 2200])
    player = {"id": "player_thief", "pos": [2000, 0, 0], "inventory": [], "ions": 2000}

    monkeypatch.setattr("mutants.commands.travel.itx._load_player", lambda: player)
    monkeypatch.setattr("mutants.commands.travel.itx._ensure_inventory", lambda _: None)
    monkeypatch.setattr(
        "mutants.commands.travel.itx._save_player",
        lambda _: pytest.fail("_save_player should not be called"),
    )
    state = {
        "players": [
            {"id": "player_thief", "pos": [2000, 0, 0], "ions": 2000},
        ],
        "active_id": "player_thief",
        "active": {"id": "player_thief", "pos": [2000, 0, 0], "ions": 2000},
        "ions": 2000,
    }
    monkeypatch.setattr("mutants.commands.travel.pstate.load_state", lambda: state)
    monkeypatch.setattr("mutants.commands.travel.pstate.save_state", lambda _: None)

    travel_cmd("2200", ctx)

    assert bus.events[-1] == (
        "SYSTEM/WARN",
        "You don't have enough ions to create a portal.",
    )
    assert ctx["render_next"] is False


def test_travel_partial_jump(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = DummyBus()

    def _loader(year: int):
        return type("W", (), {"year": year})()

    ctx = make_ctx(bus, years=[2000, 2300, 2500], loader=_loader)
    player = {"id": "player_thief", "pos": [2000, 0, 0], "inventory": [], "ions": 4000}
    state = {
        "players": [
            {"id": "player_thief", "pos": [2000, 0, 0], "ions": 4000},
        ],
        "active_id": "player_thief",
        "active": {"id": "player_thief", "pos": [2000, 0, 0], "ions": 4000},
    }
    save_calls: list[dict[str, object]] = []

    monkeypatch.setattr("mutants.commands.travel.itx._load_player", lambda: player)
    monkeypatch.setattr("mutants.commands.travel.itx._ensure_inventory", lambda _: None)
    monkeypatch.setattr(
        "mutants.commands.travel.itx._save_player",
        lambda _: pytest.fail("_save_player should not be called for travel moves"),
    )

    def _load_state() -> dict[str, object]:
        return state

    def _save_state(payload: dict[str, object]) -> None:
        snapshot = dict(payload)
        save_calls.append(snapshot)
        state.clear()
        state.update(snapshot)

    monkeypatch.setattr("mutants.commands.travel.pstate.load_state", _load_state)
    monkeypatch.setattr("mutants.commands.travel.pstate.save_state", _save_state)
    monkeypatch.setattr("mutants.commands.travel.random.choice", lambda seq: seq[1])

    travel_cmd("2550", ctx)

    assert player["ions"] == 0
    assert state["players"][0]["pos"] == [2300, 0, 0]
    assert state["active"]["pos"] == [2300, 0, 0]
    assert ctx["player_state"]["players"][0]["pos"] == [2300, 0, 0]
    assert ctx["player_state"]["active"]["pos"] == [2300, 0, 0]
    assert ctx["render_next"] is False
    assert save_calls, "expected save_state to be invoked"
    assert bus.events[-1] == (
        "SYSTEM/WARN",
        "ZAAAPPPP!!!! You suddenly feel something has gone terribly wrong!",
    )


def test_travel_no_worlds(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = DummyBus()

    def _loader(_: int):
        raise FileNotFoundError()

    ctx = make_ctx(bus, years=[2100], loader=_loader)
    player = {"id": "player_thief", "pos": [2100, 1, 2], "inventory": [], "ions": 6000}

    monkeypatch.setattr("mutants.commands.travel.itx._load_player", lambda: player)
    monkeypatch.setattr("mutants.commands.travel.itx._ensure_inventory", lambda _: None)
    monkeypatch.setattr(
        "mutants.commands.travel.itx._save_player",
        lambda _: pytest.fail("_save_player should not be called"),
    )

    travel_cmd("2150", ctx)

    assert bus.events[-1] == (
        "SYSTEM/ERROR",
        "No worlds found in state/world/.",
    )
