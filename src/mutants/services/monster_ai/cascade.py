"""Priority gate evaluation for monster actions."""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from mutants.debug import turnlog
from mutants.registries import items_instances as itemsreg
from mutants.services.combat_config import CombatConfig

LOG = logging.getLogger(__name__)

ORIGIN_WORLD = "world"


@dataclass(frozen=True)
class ActionResult:
    """Outcome of a cascade evaluation."""

    gate: str
    action: str | None
    triggered: bool
    reason: str
    roll: int | None = None
    threshold: int | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _monster_id(monster: Mapping[str, Any]) -> str:
    for key in ("id", "instance_id", "monster_id"):
        raw = monster.get(key)
        if raw is None:
            continue
        token = str(raw).strip()
        if token:
            return token
    return "?"


def _resolve_rng(ctx: Any) -> Any:
    candidate = None
    if isinstance(ctx, Mapping):
        candidate = ctx.get("monster_ai_rng")
    else:
        candidate = getattr(ctx, "monster_ai_rng", None)
    if candidate is not None and hasattr(candidate, "randrange"):
        return candidate
    rng = getattr(_resolve_rng, "_fallback", None)
    if not isinstance(rng, random.Random):
        rng = random.Random()
        setattr(_resolve_rng, "_fallback", rng)
    return rng


def _resolve_config(ctx: Any) -> CombatConfig:
    if isinstance(ctx, Mapping):
        candidate = ctx.get("combat_config")
    else:
        candidate = getattr(ctx, "combat_config", None)
    if isinstance(candidate, CombatConfig):
        return candidate
    return CombatConfig()


def _hp_pct(monster: Mapping[str, Any]) -> int:
    hp_block = monster.get("hp")
    if isinstance(hp_block, Mapping):
        current = _coerce_int(hp_block.get("current"), 0)
        maximum = _coerce_int(hp_block.get("max"), current)
    else:
        current = _coerce_int(monster.get("hp_current"), 0)
        maximum = _coerce_int(monster.get("hp_max"), max(current, 0))
    maximum = max(maximum, 1)
    pct = int(round((max(0, current) / maximum) * 100))
    return max(0, min(100, pct))


def _ions(monster: Mapping[str, Any]) -> tuple[int, int]:
    ions = _coerce_int(monster.get("ions"), 0)
    ions_max = monster.get("ions_max")
    if ions_max is None:
        ions_max = monster.get("ionsMaximum")
    ions_max = _coerce_int(ions_max, 0)
    return max(0, ions), max(0, ions_max)


def _ions_pct(ions: int, ions_max: int) -> int:
    if ions_max <= 0:
        return 100
    pct = int(round((max(0, ions) / ions_max) * 100))
    return max(0, min(100, pct))


def _bag_entries(monster: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bag = monster.get("bag")
    if isinstance(bag, Sequence) and not isinstance(bag, (str, bytes)):
        entries: list[Mapping[str, Any]] = []
        for entry in bag:
            if isinstance(entry, Mapping):
                entries.append(entry)
        return entries
    return []


def _normalized_origin(entry: Mapping[str, Any]) -> str:
    origin = entry.get("origin")
    if isinstance(origin, str):
        token = origin.strip().lower()
        if token:
            return token
    return ""


def _is_world_item(entry: Mapping[str, Any]) -> bool:
    return _normalized_origin(entry) == ORIGIN_WORLD


def _is_cracked_entry(entry: Mapping[str, Any]) -> bool:
    item_id = str(entry.get("item_id") or "").strip()
    if not item_id:
        return False
    if item_id != itemsreg.BROKEN_WEAPON_ID:
        return False
    enchant = _coerce_int(entry.get("enchant_level"), 0)
    return enchant <= 0


def _is_wielded_cracked(monster: Mapping[str, Any], bag: Sequence[Mapping[str, Any]]) -> bool:
    wielded = monster.get("wielded")
    if wielded is None:
        return False
    token = str(wielded)
    if not token:
        return False
    for entry in bag:
        iid = entry.get("iid")
        if iid is None:
            continue
        if str(iid) != token:
            continue
        if _is_cracked_entry(entry):
            return True
        return False
    return False


def _has_convertible_loot(bag: Sequence[Mapping[str, Any]]) -> bool:
    for entry in bag:
        if not _is_world_item(entry):
            continue
        item_id = str(entry.get("item_id") or "").strip()
        if not item_id:
            continue
        if item_id in {itemsreg.BROKEN_WEAPON_ID, itemsreg.BROKEN_ARMOUR_ID}:
            continue
        return True
    return False


def _sanitize_ground_items(raw: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        result: list[Mapping[str, Any]] = []
        for entry in raw:
            if isinstance(entry, Mapping):
                result.append(entry)
        return result
    return []


def _ground_items_from_ctx(ctx: Any) -> list[Mapping[str, Any]]:
    if isinstance(ctx, Mapping):
        direct = ctx.get("monster_ai_ground_items")
    else:
        direct = getattr(ctx, "monster_ai_ground_items", None)
    return _sanitize_ground_items(direct)


def _ground_items_from_registry(monster: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pos = monster.get("pos")
    if not isinstance(pos, Iterable):
        return []
    coords = list(pos)
    if len(coords) != 3:
        return []
    try:
        year, x, y = int(coords[0]), int(coords[1]), int(coords[2])
    except (TypeError, ValueError):
        return []
    list_at = getattr(itemsreg, "list_instances_at", None)
    if not callable(list_at):
        return []
    try:
        ground = list_at(year, x, y)
    except Exception:  # pragma: no cover - defensive
        return []
    return _sanitize_ground_items(ground)


def _has_pickup_candidate(monster: Mapping[str, Any], ctx: Any) -> bool:
    allow = True
    if isinstance(ctx, Mapping):
        allow = bool(ctx.get("allow_pickup", True))
    else:
        allow = bool(getattr(ctx, "allow_pickup", True))
    if not allow:
        return False

    ground = _ground_items_from_ctx(ctx)
    if not ground:
        ground = _ground_items_from_registry(monster)

    for entry in ground:
        item_id = str(entry.get("item_id") or entry.get("catalog_id") or "").strip()
        if not item_id:
            continue
        if item_id in {itemsreg.BROKEN_WEAPON_ID, itemsreg.BROKEN_ARMOUR_ID}:
            continue
        return True
    return False


def _clamp_pct(value: int) -> int:
    return max(0, min(100, value))


def _log_gate(
    ctx: Any,
    monster: Mapping[str, Any],
    gate: str,
    reason: str,
    *,
    roll: int | None,
    threshold: int | None,
    triggered: bool,
) -> None:
    meta: dict[str, Any] = {
        "monster": _monster_id(monster),
        "gate": gate,
        "triggered": triggered,
    }
    if roll is not None:
        meta["roll"] = roll
    if threshold is not None:
        meta["threshold"] = threshold
    meta["reason"] = reason
    turnlog.emit(ctx, "AI/GATE", **meta)
    LOG.info(
        "AI/GATE gate=%s roll=%s threshold=%s triggered=%s reason=%s",
        gate,
        roll if roll is not None else "-",
        threshold if threshold is not None else "-",
        triggered,
        reason,
    )


def _gate_result(
    monster: Mapping[str, Any],
    ctx: Any,
    *,
    gate: str,
    action: str | None,
    roll: int | None,
    threshold: int | None,
    reason: str,
    triggered: bool,
    data: Mapping[str, Any],
) -> ActionResult:
    _log_gate(ctx, monster, gate, reason, roll=roll, threshold=threshold, triggered=triggered)
    return ActionResult(
        gate=gate,
        action=action,
        triggered=triggered,
        reason=reason,
        roll=roll,
        threshold=threshold,
        data=data,
    )


def evaluate_cascade(monster: Any, ctx: Any) -> ActionResult:
    """Evaluate the monster action cascade and return the chosen gate."""

    if not isinstance(monster, Mapping):
        reason = "invalid-monster"
        return _gate_result(
            {"id": "?"},
            ctx,
            gate="IDLE",
            action="idle",
            roll=None,
            threshold=None,
            reason=reason,
            triggered=True,
            data={"error": reason},
        )

    config = _resolve_config(ctx)
    rng = _resolve_rng(ctx)

    bag = _bag_entries(monster)
    hp_pct = _hp_pct(monster)
    ions, ions_max = _ions(monster)
    ions_pct = _ions_pct(ions, ions_max)
    low_ions = ions_max > 0 and ions_pct < config.low_ion_pct
    cracked = _is_wielded_cracked(monster, bag)
    convertible = _has_convertible_loot(bag)
    pickup_ready = _has_pickup_candidate(monster, ctx)

    flee_threshold = _clamp_pct(config.flee_pct + (config.cracked_flee_bonus if cracked else 0))
    heal_threshold = config.heal_pct
    cast_threshold = config.cast_pct
    convert_threshold = config.convert_pct
    pickup_threshold = _clamp_pct(config.pickup_pct + (config.cracked_pickup_bonus if cracked else 0))

    if low_ions:
        convert_threshold = _clamp_pct(convert_threshold + 10)
        heal_threshold = math.floor(heal_threshold * 0.6)
        cast_threshold = math.floor(cast_threshold * 0.6)

    data_common = {
        "hp_pct": hp_pct,
        "ions_pct": ions_pct,
        "ions": ions,
        "ions_max": ions_max,
        "low_ions": low_ions,
        "cracked_weapon": cracked,
        "pickup_ready": pickup_ready,
        "convertible_loot": convertible,
    }

    failures: list[Mapping[str, Any]] = []

    def _record_failure(name: str, reason: str) -> None:
        failures.append({"gate": name, "reason": reason})

    allow_heal = True
    if isinstance(ctx, Mapping):
        allow_heal = bool(ctx.get("monster_ai_allow_heal", True))
    else:
        allow_heal = bool(getattr(ctx, "monster_ai_allow_heal", True))

    # FLEE gate
    if hp_pct < config.flee_hp_pct and flee_threshold > 0:
        roll = int(rng.randrange(100))
        reason = f"hp_pct={hp_pct} roll={roll} threshold={flee_threshold}"
        if roll < flee_threshold:
            return _gate_result(
                monster,
                ctx,
                gate="FLEE",
                action="flee",
                roll=roll,
                threshold=flee_threshold,
                reason=reason,
                triggered=True,
                data={**data_common, "failures": failures},
            )
        _record_failure("FLEE", reason)
    else:
        _record_failure("FLEE", f"hp_pct={hp_pct} threshold={flee_threshold}")

    # HEAL gate
    ions_sufficient = ions >= config.heal_cost
    if allow_heal and hp_pct < config.heal_at_pct and ions_sufficient and heal_threshold > 0:
        roll = int(rng.randrange(100))
        reason = (
            f"hp_pct={hp_pct} ions={ions} roll={roll} threshold={heal_threshold}"
        )
        if roll < heal_threshold:
            return _gate_result(
                monster,
                ctx,
                gate="HEAL",
                action="heal",
                roll=roll,
                threshold=heal_threshold,
                reason=reason,
                triggered=True,
                data={**data_common, "failures": failures},
            )
        _record_failure("HEAL", reason)
    else:
        _record_failure(
            "HEAL",
            f"hp_pct={hp_pct} ions={ions} allow_heal={allow_heal} threshold={heal_threshold}",
        )

    # CONVERT gate
    if low_ions and convertible and convert_threshold > 0:
        roll = int(rng.randrange(100))
        reason = (
            f"ions_pct={ions_pct} roll={roll} threshold={convert_threshold}"
        )
        if roll < convert_threshold:
            return _gate_result(
                monster,
                ctx,
                gate="CONVERT",
                action="convert",
                roll=roll,
                threshold=convert_threshold,
                reason=reason,
                triggered=True,
                data={**data_common, "failures": failures},
            )
        _record_failure("CONVERT", reason)
    else:
        _record_failure(
            "CONVERT",
            f"low_ions={low_ions} convertible={convertible} threshold={convert_threshold}",
        )

    # CAST gate
    if ions >= config.spell_cost and cast_threshold > 0:
        roll = int(rng.randrange(100))
        reason = (
            f"ions={ions} roll={roll} threshold={cast_threshold}"
        )
        if roll < cast_threshold:
            return _gate_result(
                monster,
                ctx,
                gate="CAST",
                action="cast",
                roll=roll,
                threshold=cast_threshold,
                reason=reason,
                triggered=True,
                data={**data_common, "failures": failures},
            )
        _record_failure("CAST", reason)
    else:
        _record_failure(
            "CAST",
            f"ions={ions} threshold={cast_threshold}",
        )

    # ATTACK gate (always available when reached)
    attack_threshold_value = config.attack_pct
    if cracked:
        attack_threshold_value = math.floor(attack_threshold_value * 0.5)
    attack_threshold = _clamp_pct(attack_threshold_value)
    if attack_threshold > 0:
        roll = int(rng.randrange(100))
        reason = f"roll={roll} threshold={attack_threshold}"
        if roll < attack_threshold:
            return _gate_result(
                monster,
                ctx,
                gate="ATTACK",
                action="attack",
                roll=roll,
                threshold=attack_threshold,
                reason=reason,
                triggered=True,
                data={**data_common, "failures": failures},
            )
        _record_failure("ATTACK", reason)
    else:
        _record_failure("ATTACK", f"threshold={attack_threshold}")

    # PICKUP gate
    if pickup_ready and pickup_threshold > 0:
        roll = int(rng.randrange(100))
        reason = f"pickup_ready={pickup_ready} roll={roll} threshold={pickup_threshold}"
        if roll < pickup_threshold:
            return _gate_result(
                monster,
                ctx,
                gate="PICKUP",
                action="pickup",
                roll=roll,
                threshold=pickup_threshold,
                reason=reason,
                triggered=True,
                data={**data_common, "failures": failures},
            )
        _record_failure("PICKUP", reason)
    else:
        _record_failure(
            "PICKUP",
            f"pickup_ready={pickup_ready} threshold={pickup_threshold}",
        )

    # EMOTE gate
    emote_threshold = _clamp_pct(config.emote_pct)
    if emote_threshold > 0:
        roll = int(rng.randrange(100))
        reason = f"roll={roll} threshold={emote_threshold}"
        if roll < emote_threshold:
            return _gate_result(
                monster,
                ctx,
                gate="EMOTE",
                action="emote",
                roll=roll,
                threshold=emote_threshold,
                reason=reason,
                triggered=True,
                data={**data_common, "failures": failures},
            )
        _record_failure("EMOTE", reason)
    else:
        _record_failure("EMOTE", f"threshold={emote_threshold}")

    # IDLE gate (fallback)
    reason = ", ".join(f"{entry['gate']}:{entry['reason']}" for entry in failures)
    if not reason:
        reason = "no-gate-triggered"
    return _gate_result(
        monster,
        ctx,
        gate="IDLE",
        action="idle",
        roll=None,
        threshold=None,
        reason=reason,
        triggered=True,
        data={**data_common, "failures": failures},
    )


__all__ = ["ActionResult", "evaluate_cascade"]
