"""Pursuit helpers for monster AI movement."""

from __future__ import annotations

import logging
import random
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from mutants.debug import turnlog
from mutants.engine import edge_resolver
from mutants.registries import dynamics as dynamics_registry
from mutants.registries import items_instances as itemsreg
from mutants.registries import world as world_registry
from mutants.services import combat_loot
from mutants.services import monsters_state
from mutants.services.combat_config import CombatConfig
from mutants.world import years as world_years

LOG = logging.getLogger(__name__)

_BASE_CHANCE = 70
_HP_DISTRACTION_THRESHOLD = 40
_LOOT_DISTRACTION_PENALTY = 20
_ION_DISTRACTION_PENALTY = 15
_HP_DISTRACTION_PENALTY = 20
_CRACKED_DISTRACTION_PENALTY = 25

_DIRECTIONS = {
    (1, 0): "E",
    (-1, 0): "W",
    (0, 1): "N",
    (0, -1): "S",
}


def _monster_id(monster: Mapping[str, Any]) -> str:
    for key in ("id", "instance_id", "monster_id"):
        raw = monster.get(key)
        if raw is None:
            continue
        token = str(raw).strip()
        if token:
            return token
    return "?"


def _bag_entries(monster: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bag = monster.get("bag")
    if isinstance(bag, Sequence) and not isinstance(bag, (str, bytes)):
        entries: list[Mapping[str, Any]] = []
        for entry in bag:
            if isinstance(entry, Mapping):
                entries.append(entry)
        return entries
    return []


def _is_cracked_entry(entry: Mapping[str, Any]) -> bool:
    item_id = str(entry.get("item_id") or entry.get("catalog_id") or "").strip()
    if not item_id:
        return False
    if item_id != itemsreg.BROKEN_WEAPON_ID:
        return False
    enchant = entry.get("enchant_level")
    try:
        enchant_val = int(enchant)
    except (TypeError, ValueError):
        enchant_val = 0
    return enchant_val <= 0


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
        return _is_cracked_entry(entry)
    return False


def _ground_items(monster: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pos = combat_loot.coerce_pos(monster.get("pos"))
    if pos is None:
        return []
    year, x, y = pos
    list_at = getattr(itemsreg, "list_instances_at", None)
    if not callable(list_at):
        return []
    try:
        items = list_at(year, x, y)
    except Exception:  # pragma: no cover - defensive
        return []
    result: list[Mapping[str, Any]] = []
    if isinstance(items, Iterable):
        for entry in items:
            if isinstance(entry, Mapping):
                result.append(entry)
    return result


def _has_pickup_candidate(monster: Mapping[str, Any]) -> bool:
    for entry in _ground_items(monster):
        item_id = str(entry.get("item_id") or entry.get("catalog_id") or "").strip()
        if not item_id:
            continue
        if item_id in {itemsreg.BROKEN_WEAPON_ID, itemsreg.BROKEN_ARMOUR_ID}:
            continue
        return True
    return False


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hp_pct(monster: Mapping[str, Any]) -> int:
    hp_block = monster.get("hp")
    if isinstance(hp_block, Mapping):
        current = _coerce_int(hp_block.get("current"), 0)
        maximum = _coerce_int(hp_block.get("max"), max(current, 1))
    else:
        current = _coerce_int(monster.get("hp_current"), 0)
        maximum = _coerce_int(monster.get("hp_max"), max(current, 1))
    maximum = max(1, maximum)
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


def _clamp_pct(value: int) -> int:
    return max(0, min(100, value))


def _resolve_world_loader(ctx: Any) -> Any:
    candidate = None
    if isinstance(ctx, Mapping):
        candidate = ctx.get("monster_ai_world_loader")
    else:
        candidate = getattr(ctx, "monster_ai_world_loader", None)
    if callable(candidate):
        return candidate
    return world_registry.load_year


def _resolve_dynamics(ctx: Any) -> Any:
    if isinstance(ctx, Mapping):
        candidate = ctx.get("monster_ai_dynamics")
    else:
        candidate = getattr(ctx, "monster_ai_dynamics", None)
    return candidate if candidate is not None else dynamics_registry


def _log(ctx: Any, monster: Mapping[str, Any], *, success: bool, reason: str, **meta: Any) -> None:
    payload = {"monster": _monster_id(monster), "success": success, "reason": reason}
    payload.update(meta)
    turnlog.emit(ctx, "AI/PURSUIT", **payload)
    if success:
        LOG.info("AI/PURSUIT success=%s reason=%s meta=%s", success, reason, {k: meta[k] for k in sorted(meta)})
    else:
        LOG.debug("AI/PURSUIT success=%s reason=%s meta=%s", success, reason, {k: meta[k] for k in sorted(meta)})


def _apply_movement(
    monster: MutableMapping[str, Any],
    year: int,
    start: tuple[int, int],
    target: tuple[int, int],
    ctx: Any,
) -> tuple[bool, dict[str, Any]]:
    loader = _resolve_world_loader(ctx)
    dynamics = _resolve_dynamics(ctx)
    try:
        world = loader(year)
    except Exception:
        return False, {"reason": "world-unavailable"}

    sx, sy = start
    tx, ty = target
    dx = tx - sx
    dy = ty - sy

    details: dict[str, Any] = {"from": start, "target": target}

    step_taken: tuple[int, int] | None = None

    direction = _DIRECTIONS.get((dx, dy))
    if direction is not None:
        decision = edge_resolver.resolve(
            world,
            dynamics,
            year,
            sx,
            sy,
            direction,
            actor={"kind": "monster"},
        )
        details["direct_reason"] = decision.reason
        if decision.passable:
            step_taken = (tx, ty)
            details.update({"mode": "direct", "step": step_taken, "dir": direction})
    else:
        details["mode"] = "non-adjacent"

    if step_taken is None:
        path = world_years.find_path_between(
            year,
            start,
            target,
            world=world,
            dynamics=dynamics,
        )
        if len(path) >= 2:
            step_taken = path[1]
            details.update({"mode": "path", "step": step_taken, "path_len": len(path)})
        else:
            details.setdefault("path_len", len(path))
            details.setdefault("mode", "blocked")
            details.setdefault("reason", details.get("direct_reason", "blocked"))
            return False, details

    monster["pos"] = [year, step_taken[0], step_taken[1]]
    monsters_state._refresh_monster_derived(monster)
    return True, details


def attempt_pursuit(
    monster: MutableMapping[str, Any],
    target_pos: Iterable[int] | Mapping[str, Any],
    rng: Any,
    *,
    ctx: Any | None = None,
    config: CombatConfig | None = None,
) -> bool:
    """Attempt to move ``monster`` toward ``target_pos`` using pursuit rules."""

    pos = combat_loot.coerce_pos(monster.get("pos"))
    target = combat_loot.coerce_pos(target_pos)
    if pos is None or target is None:
        _log(ctx, monster, success=False, reason="invalid-pos", pos=pos, target=target)
        return False

    year, sx, sy = pos
    t_year, tx, ty = target
    if int(year) != int(t_year):
        _log(ctx, monster, success=False, reason="cross-year", pos=pos, target=target)
        return False

    config_obj = config if isinstance(config, CombatConfig) else CombatConfig()

    bag = _bag_entries(monster)
    modifiers: list[str] = []
    chance = _BASE_CHANCE

    if _has_pickup_candidate(monster):
        chance -= _LOOT_DISTRACTION_PENALTY
        modifiers.append("loot")

    ions, ions_max = _ions(monster)
    ions_pct = _ions_pct(ions, ions_max)
    if ions_max > 0 and ions_pct < config_obj.low_ion_pct:
        chance -= _ION_DISTRACTION_PENALTY
        modifiers.append("low_ions")

    hp_pct = _hp_pct(monster)
    if hp_pct < _HP_DISTRACTION_THRESHOLD:
        chance -= _HP_DISTRACTION_PENALTY
        modifiers.append("low_hp")

    if _is_wielded_cracked(monster, bag):
        chance -= _CRACKED_DISTRACTION_PENALTY
        modifiers.append("cracked")

    threshold = _clamp_pct(chance)
    try:
        roll = int(rng.randrange(100))
    except Exception:
        roll = int(random.Random().randrange(100))

    meta = {
        "threshold": threshold,
        "roll": roll,
        "modifiers": tuple(modifiers),
        "hp_pct": hp_pct,
        "ions_pct": ions_pct,
        "ions": ions,
        "ions_max": ions_max,
    }

    if roll >= threshold:
        reason = f"roll={roll} threshold={threshold}"
        _log(ctx, monster, success=False, reason=reason, **meta)
        return False

    success, details = _apply_movement(monster, int(year), (int(sx), int(sy)), (int(tx), int(ty)), ctx)
    if success:
        meta.update(details)
        _log(ctx, monster, success=True, reason="moved", **meta)
        return True

    meta.update(details)
    _log(ctx, monster, success=False, reason=details.get("reason", details.get("direct_reason", "blocked")), **meta)
    return False


__all__ = ["attempt_pursuit"]
