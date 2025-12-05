"""Attack type selection logic for the monster AI."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from mutants.registries import items_catalog, items_instances as itemsreg


@dataclass(frozen=True)
class AttackPlan:
    """Describe the chosen attack source and weapon identifier."""

    source: str
    item_iid: str | None = None


def _resolve_rng(ctx: Any) -> Any:
    """Return a RNG compatible with :func:`random.Random.randrange`."""

    candidate = None
    if isinstance(ctx, Mapping):
        candidate = ctx.get("monster_ai_rng")
    else:  # pragma: no cover - defensive
        candidate = getattr(ctx, "monster_ai_rng", None)
    if candidate is not None and hasattr(candidate, "randrange"):
        return candidate
    fallback = getattr(_resolve_rng, "_fallback", None)
    if not isinstance(fallback, random.Random):
        fallback = random.Random()
        setattr(_resolve_rng, "_fallback", fallback)
    return fallback


def _bag_entries(monster: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bag = monster.get("bag")
    if isinstance(bag, Sequence) and not isinstance(bag, (str, bytes)):
        entries: list[Mapping[str, Any]] = []
        for entry in bag:
            if isinstance(entry, Mapping):
                entries.append(entry)
        return entries
    return []


def _normalize_token(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return None


def _resolve_prefers_ranged(monster: Mapping[str, Any], ctx: Any) -> bool:
    candidates: list[Any] = []
    if isinstance(ctx, Mapping):
        candidates.append(ctx.get("monster_ai_prefers_ranged"))
    else:  # pragma: no cover - defensive
        candidates.append(getattr(ctx, "monster_ai_prefers_ranged", None))
    candidates.append(monster.get("prefers_ranged"))
    state = monster.get("_ai_state")
    if isinstance(state, Mapping):
        candidates.append(state.get("prefers_ranged"))
    for raw in candidates:
        coerced = _coerce_bool(raw)
        if coerced is not None:
            return coerced
    return False


def _resolve_item_id(entry: Mapping[str, Any]) -> str:
    for key in ("item_id", "catalog_id", "id"):
        raw = entry.get(key)
        token = _normalize_token(raw)
        if token:
            return token
    iid = entry.get("iid") or entry.get("instance_id")
    token = _normalize_token(iid)
    if not token:
        return ""
    inst = itemsreg.get_instance(token)
    if isinstance(inst, Mapping):
        for key in ("item_id", "catalog_id", "id"):
            raw = inst.get(key)
            resolved = _normalize_token(raw)
            if resolved:
                return resolved
    return ""


def _load_catalog() -> Mapping[str, Mapping[str, Any]]:
    try:
        catalog = items_catalog.load_catalog()
    except FileNotFoundError:  # pragma: no cover - defensive
        catalog = None
    if isinstance(catalog, Mapping):
        return catalog
    return {}


def _entry_template(entry: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    item_id = _resolve_item_id(entry)
    if not item_id:
        return {}
    template = catalog.get(item_id)
    if isinstance(template, Mapping):
        return template
    return {}


def _is_ranged_entry(entry: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]) -> bool:
    direct = entry.get("ranged")
    if direct is not None:
        return bool(direct)
    template = _entry_template(entry, catalog)
    return bool(template.get("ranged"))


def _is_weapon_entry(entry: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]) -> bool:
    template = _entry_template(entry, catalog)
    if template.get("armour"):
        return False
    item_id = _resolve_item_id(entry)
    if not item_id:
        derived = entry.get("derived")
        if isinstance(derived, Mapping) and derived.get("base_damage") is not None:
            return True
        return False
    if item_id == itemsreg.BROKEN_ARMOUR_ID:
        return False
    if item_id == itemsreg.BROKEN_WEAPON_ID:
        return True
    return not bool(template.get("armour"))


def _find_wielded_entry(monster: Mapping[str, Any], bag: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    token = _normalize_token(monster.get("wielded"))
    if not token:
        return None
    for entry in bag:
        iid = _normalize_token(entry.get("iid") or entry.get("instance_id"))
        if iid and iid == token:
            return entry
    for entry in bag:
        item_id = _resolve_item_id(entry)
        if item_id and item_id == token:
            return entry
    return None


def _find_entry(
    bag: Sequence[Mapping[str, Any]],
    predicate: Callable[[Mapping[str, Any]], bool],
    preferred: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if preferred is not None and predicate(preferred):
        return preferred
    for entry in bag:
        if predicate(entry):
            return entry
    return None


def _has_innate(monster: Mapping[str, Any]) -> bool:
    innate = monster.get("innate_attack")
    if isinstance(innate, Mapping):
        return bool(innate)
    return bool(innate)


def _melee_power(entry: Mapping[str, Any] | None, catalog: Mapping[str, Mapping[str, Any]]) -> int:
    if not entry:
        return 0
    derived = entry.get("derived")
    if isinstance(derived, Mapping) and derived.get("base_damage") is not None:
        try:
            return max(0, int(derived.get("base_damage", 0)))
        except (TypeError, ValueError):
            return 0
    template = _entry_template(entry, catalog)
    try:
        return max(0, int(template.get("base_power_melee", 0)))
    except (TypeError, ValueError):
        return 0


def _innate_power(monster: Mapping[str, Any]) -> int:
    innate = monster.get("innate_attack")
    if not isinstance(innate, Mapping):
        return 0
    for key in ("base_power", "base_damage", "base_power_melee"):
        if key in innate:
            try:
                return max(0, int(innate.get(key, 0)))
            except (TypeError, ValueError):
                return 0
    return 0


def _entry_token(entry: Mapping[str, Any] | None, fallback: str | None = None) -> str | None:
    if entry is None:
        return fallback
    for key in ("iid", "instance_id"):
        token = _normalize_token(entry.get(key))
        if token:
            return token
    item_id = _resolve_item_id(entry)
    return item_id or fallback


def _is_cracked_entry(entry: Mapping[str, Any]) -> bool:
    item_id = _resolve_item_id(entry)
    if item_id != itemsreg.BROKEN_WEAPON_ID:
        return False
    enchant = entry.get("enchant_level")
    try:
        level = int(enchant)
    except (TypeError, ValueError):
        level = 0
    return level <= 0


def _apply_cracked_penalty(weight: int, entry: Mapping[str, Any] | None) -> int:
    if weight <= 0 or entry is None:
        return weight
    if not _is_cracked_entry(entry):
        return weight
    adjusted = int(weight * 0.75)
    if weight > 0 and adjusted <= 0:
        return 1
    return adjusted


def _build_weight_table(
    *,
    melee_entry: Mapping[str, Any] | None,
    ranged_entry: Mapping[str, Any] | None,
    has_innate: bool,
    prefers_ranged: bool,
    melee_power: int,
    innate_power: int,
) -> dict[str, int]:
    weights: dict[str, int] = {"melee": 0, "bolt": 0, "innate": 0}
    if melee_entry and ranged_entry:
        if prefers_ranged:
            weights["melee"] = 20
            weights["bolt"] = 70
        else:
            weights["melee"] = 70
            weights["bolt"] = 20
        if has_innate:
            weights["innate"] = 10
    elif melee_entry:
        weights["melee"] = 95
        if has_innate:
            weights["innate"] = 5
    elif ranged_entry:
        weights["bolt"] = 95 if prefers_ranged else 90
        if has_innate:
            weights["innate"] = 5 if prefers_ranged else 10
    else:
        if has_innate:
            weights["innate"] = 100
    if has_innate and melee_entry:
        # If the melee option is notably weaker than innate, favour innate.
        if melee_power < max(1, int(innate_power * 0.75)):
            weights["innate"] = max(weights["innate"], 90)
            weights["melee"] = min(weights["melee"], 10)
    return weights


def select_attack(monster: Mapping[str, Any], ctx: Any) -> AttackPlan:
    """Return an :class:`AttackPlan` describing the chosen attack source."""

    bag = _bag_entries(monster)
    catalog = _load_catalog()
    wielded_entry = _find_wielded_entry(monster, bag)

    melee_entry = _find_entry(
        bag,
        lambda entry: _is_weapon_entry(entry, catalog) and not _is_ranged_entry(entry, catalog),
        preferred=wielded_entry if wielded_entry and not _is_ranged_entry(wielded_entry, catalog) else None,
    )
    ranged_entry = _find_entry(
        bag,
        lambda entry: _is_weapon_entry(entry, catalog) and _is_ranged_entry(entry, catalog),
        preferred=wielded_entry if wielded_entry and _is_ranged_entry(wielded_entry, catalog) else None,
    )

    has_innate = _has_innate(monster)
    prefers_ranged = _resolve_prefers_ranged(monster, ctx)
    melee_power = _melee_power(melee_entry, catalog)
    innate_power = _innate_power(monster)

    weights = _build_weight_table(
        melee_entry=melee_entry,
        ranged_entry=ranged_entry,
        has_innate=has_innate,
        prefers_ranged=prefers_ranged,
        melee_power=melee_power,
        innate_power=innate_power,
    )

    weights["melee"] = _apply_cracked_penalty(weights["melee"], melee_entry)
    weights["bolt"] = _apply_cracked_penalty(weights["bolt"], ranged_entry)

    weighted_sources: list[tuple[str, int]] = []
    for source in ("melee", "bolt", "innate"):
        weight = int(weights.get(source, 0))
        if weight > 0:
            weighted_sources.append((source, weight))

    if not weighted_sources:
        # No usable weapons or innate attack – fall back to innate punch.
        return AttackPlan("innate", None)

    if len(weighted_sources) == 1:
        selected_source = weighted_sources[0][0]
    else:
        total = sum(weight for _, weight in weighted_sources)
        rng = _resolve_rng(ctx)
        roll = 0
        if total > 0:
            roll = int(rng.randrange(total))
        cumulative = 0
        selected_source = weighted_sources[-1][0]
        for source, weight in weighted_sources:
            cumulative += weight
            if roll < cumulative:
                selected_source = source
                break

    wielded_token = _normalize_token(monster.get("wielded"))
    if selected_source == "melee":
        iid = _entry_token(melee_entry, fallback=wielded_token)
        return AttackPlan("melee", iid)
    if selected_source == "bolt":
        iid = _entry_token(ranged_entry, fallback=wielded_token)
        return AttackPlan("bolt", iid)
    return AttackPlan("innate", None)

