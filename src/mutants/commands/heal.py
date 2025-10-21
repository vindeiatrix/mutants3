from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict

from mutants.services import player_state as pstate
from mutants.debug import turnlog


_ION_MULTIPLIERS: Dict[str, int] = {
    "warrior": 750,
    "priest": 750,
    "mage": 1_200,
    "wizard": 1_000,
    "thief": 200,
    "default": 200,
}
_DEFAULT_MULTIPLIER = _ION_MULTIPLIERS["default"]


def _class_multiplier(name: str, table: Mapping[str, int]) -> int:
    normalized = name.strip().lower() if isinstance(name, str) else ""
    default = table.get("default", _DEFAULT_MULTIPLIER)
    return table.get(normalized, default)


def _heal_cost_multipliers(ctx: Mapping[str, Any]) -> Mapping[str, int]:
    config = ctx.get("combat_config") if hasattr(ctx, "get") else None
    table = getattr(config, "heal_cost_multiplier", None)
    if isinstance(table, Mapping):
        return table
    return _ION_MULTIPLIERS


def heal_cmd(arg: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    bus = ctx["feedback_bus"]
    try:
        state = pstate.load_state()
    except Exception:
        state = ctx.get("player_state")

    if not isinstance(state, dict):
        bus.push("SYSTEM/ERROR", "No player state available to heal.")
        return {"ok": False, "reason": "state_unavailable"}

    klass = pstate.get_active_class(state)
    level = pstate.get_level_for_active(state)
    hp_block = pstate.get_hp_for_active(state)
    current_hp = hp_block.get("current", 0)
    max_hp = hp_block.get("max", 0)
    if max_hp <= 0:
        bus.push("SYSTEM/WARN", "You cannot heal right now.")
        return {"ok": False, "reason": "no_max_hp"}
    missing = max(0, max_hp - current_hp)
    if missing <= 0:
        bus.push("SYSTEM/OK", "You're already at full health.")
        return {"ok": False, "reason": "full_health"}

    multipliers = _heal_cost_multipliers(ctx)
    cost = _class_multiplier(klass, multipliers) * max(1, level)
    available_ions = pstate.get_ions_for_active(state)
    if available_ions < cost:
        bus.push(
            "SYSTEM/WARN",
            f"You need {cost:,} ions to heal but only have {available_ions:,}.",
        )
        return {
            "ok": False,
            "reason": "insufficient_ions",
            "required": cost,
            "available": available_ions,
        }

    heal_points = max(0, level + 5)
    healed, updated_hp = pstate.heal_active(state, heal_points)
    if healed <= 0:
        bus.push("SYSTEM/OK", "You're already at full health.")
        return {"ok": False, "reason": "full_health"}

    success, remaining_ions = pstate.spend_ions_for_active(state, cost)
    if not success:
        # Fallback in case the balance changed between checks.
        bus.push(
            "SYSTEM/WARN",
            f"You need {cost:,} ions to heal but only have {available_ions:,}.",
        )
        return {
            "ok": False,
            "reason": "insufficient_ions",
            "required": cost,
            "available": available_ions,
        }

    try:
        ctx["player_state"] = pstate.load_state()
    except Exception:
        ctx["player_state"] = state

    bus.push(
        "SYSTEM/OK",
        f"You restore {healed} hit points ({cost:,} ions).",
    )
    turnlog.emit(
        ctx,
        "COMBAT/HEAL",
        actor="player",
        hp_restored=healed,
        ions_spent=cost,
    )
    return {
        "ok": True,
        "healed": healed,
        "cost": cost,
        "remaining_ions": remaining_ions,
        "hp": updated_hp,
    }


def register(dispatch, ctx) -> None:
    dispatch.register("heal", lambda arg: heal_cmd(arg, ctx))
