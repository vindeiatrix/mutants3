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


def _ranged_power(entry: Mapping[str, Any] | None, catalog: Mapping[str, Mapping[str, Any]]) -> int:
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
        return max(0, int(template.get("base_power_bolt", 0)))
    except (TypeError, ValueError):
        return 0


def _innate_power(monster: Mapping[str, Any]) -> int:
    innate = monster.get("innate_attack")
    if not isinstance(innate, Mapping):
        return 0
    for key in ("base_power", "base_damage", "base_power_melee", "power_base"):
        if key in innate:
            try:
                return max(0, int(innate.get(key, 0)))
            except (TypeError, ValueError):
                return 0
    return 0


def _resolve_prefers_innate(monster: Mapping[str, Any], ctx: Any) -> bool:
    overrides = monster.get("ai_overrides")
    if isinstance(overrides, Mapping):
        flag = overrides.get("prefers_innate")
        if isinstance(flag, bool):
            return flag
    state = monster.get("_ai_state")
    if isinstance(state, Mapping):
        flag = state.get("prefers_innate")
        if isinstance(flag, bool):
            return flag
    return False


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
    ranged_power: int,
    innate_power: int,
    prefers_innate: bool,
    melee_is_skull: bool,
) -> dict[str, int]:
    melee_w = max(0, melee_power)
    ranged_w = max(0, ranged_power)
    innate_w = max(0, innate_power if has_innate else 0)

    if melee_is_skull and innate_w > 0:
        melee_w = min(melee_w, max(1, melee_w // 5))
        innate_w = max(innate_w, 90)

    if melee_w > 0 and ranged_w > 0:
        if prefers_ranged or ranged_w > melee_w * 1.1:
            melee_w = max(10, melee_w)
            ranged_w = max(20, ranged_w)
        else:
            melee_w = max(20, melee_w)
            ranged_w = max(10, ranged_w)
    elif melee_w > 0:
        melee_w = max(20, melee_w * 2)
    elif ranged_w > 0:
        ranged_w = max(20, ranged_w * 2)

    if prefers_ranged and ranged_w > 0:
        ranged_w = int(ranged_w * 1.2)
    if prefers_innate and innate_w > 0:
        innate_w = int(innate_w * 1.3)

    if has_innate and melee_w > 0 and innate_w > 0:
        if melee_power < max(1, int(innate_power * 0.75)):
            innate_w = max(innate_w, 90)
            melee_w = min(melee_w, 10)

    if melee_w == 0 and ranged_w == 0 and innate_w == 0 and has_innate:
        innate_w = 100

    return {"melee": melee_w, "bolt": ranged_w, "innate": innate_w}


def select_attack(monster: Mapping[str, Any], ctx: Any) -> AttackPlan:
    """Return an :class:`AttackPlan` describing the chosen attack source."""

    bag = _bag_entries(monster)
    catalog = _load_catalog()
    wielded_entry = _find_wielded_entry(monster, bag)

    melee_entry = None
    ranged_entry = None
    best_melee_score = -1
    best_ranged_score = -1
    wielded_iid = _normalize_token(wielded_entry.get("iid") or wielded_entry.get("instance_id")) if wielded_entry else None

    for entry in bag:
        if not isinstance(entry, Mapping):
            continue
        if _is_weapon_entry(entry, catalog) and not _is_ranged_entry(entry, catalog):
            score = _melee_power(entry, catalog)
            score = _apply_cracked_penalty(score, entry)
            preferred = wielded_iid and _normalize_token(entry.get("iid") or entry.get("instance_id")) == wielded_iid
            if score > best_melee_score or (score == best_melee_score and preferred):
                best_melee_score = score
                melee_entry = entry
        if _is_weapon_entry(entry, catalog) and _is_ranged_entry(entry, catalog):
            score = _ranged_power(entry, catalog)
            score = _apply_cracked_penalty(score, entry)
            preferred = wielded_iid and _normalize_token(entry.get("iid") or entry.get("instance_id")) == wielded_iid
            if score > best_ranged_score or (score == best_ranged_score and preferred):
                best_ranged_score = score
                ranged_entry = entry

    has_innate = _has_innate(monster)
    prefers_ranged = _resolve_prefers_ranged(monster, ctx)
    prefers_innate = _resolve_prefers_innate(monster, ctx)
    melee_power = max(0, best_melee_score)
    ranged_power = max(0, best_ranged_score)
    innate_power = _innate_power(monster)
    melee_is_skull = _resolve_item_id(melee_entry or {}) == "skull"

    weights = _build_weight_table(
        melee_entry=melee_entry,
        ranged_entry=ranged_entry,
        has_innate=has_innate,
        prefers_ranged=prefers_ranged,
        melee_power=melee_power,
        ranged_power=ranged_power,
        innate_power=innate_power,
        prefers_innate=prefers_innate,
        melee_is_skull=melee_is_skull,
    )

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

