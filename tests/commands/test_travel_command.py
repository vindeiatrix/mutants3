from __future__ import annotations

import pytest

from mutants.commands.travel import _floor_to_century, _parse_year, travel_cmd


class DummyBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def push(self, kind: str, text: str, **_: object) -> None:
        self.events.append((kind, text))


class DummyWorld:
    def __init__(self, year: int) -> None:
        self.year = year


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


def test_travel_requires_year() -> None:
    ctx = {"feedback_bus": DummyBus(), "render_next": False, "peek_vm": object()}
    travel_cmd("", ctx)
    assert ctx["feedback_bus"].events[-1] == (
        "SYSTEM/WARN", "Usage: TRAVEL <year>  (e.g., 'tra 2100')."
    )
    assert ctx["render_next"] is False
    assert ctx["peek_vm"] is not None


def test_travel_no_worlds(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = {
        "feedback_bus": DummyBus(),
        "world_loader": lambda year: (_ for _ in ()).throw(FileNotFoundError()),
        "render_next": False,
        "peek_vm": object(),
    }

    # Ensure player load/save helpers are not called.
    monkeypatch.setattr(
        "mutants.commands.travel.itx._load_player",
        lambda: pytest.fail("should not load player"),
    )

    travel_cmd("2300", ctx)
    assert ctx["feedback_bus"].events[-1] == (
        "SYSTEM/ERROR",
        "No worlds found in state/world/.",
    )
    assert ctx["render_next"] is False


def test_travel_updates_player_state(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = DummyBus()
    ctx: dict[str, object] = {
        "feedback_bus": bus,
        "world_loader": lambda year: DummyWorld(2400),
        "render_next": False,
        "peek_vm": "not-none",
    }

    player = {"id": "player_thief", "pos": [2000, 3, 4], "inventory": []}
    saved: dict[str, object] = {}

    monkeypatch.setattr("mutants.commands.travel.itx._load_player", lambda: player)
    monkeypatch.setattr("mutants.commands.travel.itx._ensure_inventory", lambda p: None)
    monkeypatch.setattr(
        "mutants.commands.travel.itx._save_player",
        lambda payload: saved.update({"player": payload.copy()}),
    )
    new_state = {"players": [player], "active_id": "player_thief"}
    monkeypatch.setattr("mutants.commands.travel.pstate.load_state", lambda: new_state)

    travel_cmd("2356", ctx)

    assert saved["player"]["pos"] == [2400, 0, 0]
    assert ctx["player_state"] is new_state
    assert ctx["render_next"] is True
    assert ctx["peek_vm"] is None
    assert bus.events[-1] == ("SYSTEM/OK", "Travel complete. Year: 2400.")
