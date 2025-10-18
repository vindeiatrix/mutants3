from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants import state  # noqa: E402
from mutants.commands import heal  # noqa: E402
from mutants.services import combat_config, player_state  # noqa: E402
from types import MappingProxyType


class FakeBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, dict[str, object]]] = []

    def push(self, kind: str, message: str, **meta: object) -> None:
        self.messages.append((kind, message, dict(meta)))


@pytest.fixture()
def configure_state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(state, "STATE_ROOT", tmp_path)
    return tmp_path


def _write_state(
    klass: str,
    level: int,
    current_hp: int,
    max_hp: int,
    ions: int,
) -> dict:
    player_id = f"player_{klass.lower()}"
    payload = {
        "players": [
            {
                "id": player_id,
                "class": klass,
                "name": klass,
                "hp": {"current": current_hp, "max": max_hp},
                "level": level,
                "ions": ions,
                "Ions": ions,
                "pos": [2000, 0, 0],
                "inventory": [],
            }
        ],
        "active_id": player_id,
        "active": {
            "id": player_id,
            "class": klass,
            "hp": {"current": current_hp, "max": max_hp},
            "level": level,
            "ions": ions,
            "Ions": ions,
            "pos": [2000, 0, 0],
        },
        "hp_by_class": {klass: {"current": current_hp, "max": max_hp}},
        "level_by_class": {klass: level},
        "ions_by_class": {klass: ions},
    }
    player_state.save_state(payload)
    return payload


@pytest.mark.parametrize(
    ("klass", "multiplier"),
    [
        ("Warrior", 750),
        ("Priest", 750),
        ("Mage", 1_200),
        ("Wizard", 1_000),
        ("Thief", 200),
    ],
)
def test_heal_recovers_hp_and_consumes_ions(
    configure_state_root: Path,
    klass: str,
    multiplier: int,
) -> None:
    level = 4
    base_hp = 25
    max_hp = 200
    heal_amount = level + 5
    cost = level * multiplier
    starting_ions = cost + 5_000

    initial_state = _write_state(klass, level, base_hp, max_hp, starting_ions)
    ctx = {"feedback_bus": FakeBus(), "player_state": dict(initial_state)}

    result = heal.heal_cmd("", ctx)

    updated = player_state.load_state()
    updated_hp = player_state.get_hp_for_active(updated)
    remaining_ions = player_state.get_ions_for_active(updated)

    expected_heal = min(heal_amount, max_hp - base_hp)
    assert result["ok"] is True
    assert result["healed"] == expected_heal
    assert updated_hp["current"] == base_hp + expected_heal
    assert updated_hp["max"] == max_hp
    assert remaining_ions == starting_ions - cost

    assert ctx["feedback_bus"].messages[-1] == (
        "SYSTEM/OK",
        f"You restore {expected_heal} hit points ({cost:,} ions).",
        {},
    )


def test_heal_emits_turnlog_event(configure_state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    klass = "Wizard"
    level = 7
    multiplier = 1_000
    cost = level * multiplier
    base_hp = 10
    max_hp = 50
    starting_ions = cost + 100

    initial_state = _write_state(klass, level, base_hp, max_hp, starting_ions)
    ctx = {"feedback_bus": FakeBus(), "player_state": dict(initial_state)}

    captured: list[tuple[str, dict[str, int | str]]] = []

    def fake_emit(local_ctx, kind: str, **meta):
        captured.append((kind, dict(meta)))

    monkeypatch.setattr(heal.turnlog, "emit", fake_emit)

    result = heal.heal_cmd("", ctx)

    assert result["ok"] is True
    assert captured
    kind, payload = captured[-1]
    assert kind == "COMBAT/HEAL"
    assert payload["actor"] == "player"
    assert payload["hp_restored"] == result["healed"]
    assert payload["ions_spent"] == cost


def test_heal_rejects_when_ions_insufficient(configure_state_root: Path) -> None:
    klass = "Wizard"
    level = 3
    multiplier = 1_000
    cost = level * multiplier
    starting_ions = cost - 1

    initial_state = _write_state(klass, level, 10, 40, starting_ions)
    ctx = {"feedback_bus": FakeBus(), "player_state": dict(initial_state)}

    result = heal.heal_cmd("", ctx)

    updated = player_state.load_state()
    updated_hp = player_state.get_hp_for_active(updated)
    remaining_ions = player_state.get_ions_for_active(updated)

    assert result["ok"] is False
    assert result["reason"] == "insufficient_ions"
    assert updated_hp["current"] == 10
    assert remaining_ions == starting_ions
    assert ctx["feedback_bus"].messages[-1][0] == "SYSTEM/WARN"
    assert f"{cost:,}" in ctx["feedback_bus"].messages[-1][1]


def test_heal_cost_uses_combat_config_override(configure_state_root: Path) -> None:
    klass = "Wizard"
    level = 5
    override_multiplier = 321
    base_hp = 50
    max_hp = 200
    starting_ions = override_multiplier * level + 1_000

    initial_state = _write_state(klass, level, base_hp, max_hp, starting_ions)

    overrides = dict(combat_config.CombatConfig().heal_cost_multiplier)
    overrides[klass.lower()] = override_multiplier
    config = replace(
        combat_config.CombatConfig(),
        heal_cost_multiplier=MappingProxyType(overrides),
    )

    ctx = {
        "feedback_bus": FakeBus(),
        "player_state": dict(initial_state),
        "combat_config": config,
    }

    result = heal.heal_cmd("", ctx)

    assert result["ok"] is True
    assert result["cost"] == override_multiplier * level
    assert ctx["feedback_bus"].messages[-1][1].endswith(
        f"({override_multiplier * level:,} ions)."
    )
