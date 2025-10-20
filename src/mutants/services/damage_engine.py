"""Utilities for resolving combat damage.

This module wraps item registry lookups, player state helpers, and armour calculations to
produce deterministic attack results. Public functions follow NumPy docstring style so
they render cleanly in the MkDocs API reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Optional

from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import combat_calc, player_state as pstate


def _coerce_int(value: Any, default: int = 0) -> int:
    """Best-effort conversion of ``value`` to ``int`` with ``default`` fallback."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_mapping(payload: Any) -> MutableMapping[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


def _resolve_instance_id(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("iid", "instance_id"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _resolve_item_id(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("item_id", "catalog_id", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _resolve_item_template(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    item_id = _resolve_item_id(payload)
    if not item_id:
        return {}

    try:
        catalog = items_catalog.load_catalog()
    except FileNotFoundError:
        return {}

    template = catalog.get(item_id)
    if not isinstance(template, Mapping):
        return {}

    return template


def _normalize_source(token: Optional[str]) -> str:
    if isinstance(token, str):
        lowered = token.strip().lower()
        if lowered in {"innate", "bolt", "melee"}:
            return lowered
    return "melee"


def _resolve_attack_source(
    payload: Mapping[str, Any],
    template: Mapping[str, Any],
    *,
    hint: Optional[str] = None,
) -> str:
    if hint:
        normalized = _normalize_source(hint)
        if normalized:
            return normalized

    hinted = payload.get("attack_source")
    normalized = _normalize_source(hinted if isinstance(hinted, str) else None)
    if normalized != "melee":
        return normalized

    if not _resolve_item_id(payload):
        return "innate"

    return "melee"


def _resolve_base_power(
    payload: Mapping[str, Any],
    template: Mapping[str, Any],
    *,
    source: str,
) -> int:
    if not payload and not template:
        return 0

    if source == "bolt":
        field_order = ("base_power_bolt", "power_bolt", "base_power")
    else:
        field_order = ("base_power_melee", "power_base", "base_power")

    for field in field_order:
        if field in payload:
            return max(0, _coerce_int(payload.get(field), 0))

    for field in field_order:
        if field in template:
            return max(0, _coerce_int(template.get(field), 0))

    return 0


@dataclass
class _AttackContext:
    payload: MutableMapping[str, Any]
    template: Mapping[str, Any]
    source: str
    base_power: int
    enchant_level: int
    strength_bonus: int


def apply_ac_mitigation(raw_damage: int, ac: int) -> int:
    """Return ``raw_damage`` reduced by the AC mitigation curve."""

    base_damage = _coerce_int(raw_damage, 0)
    armour_class = max(0, _coerce_int(ac, 0))
    mitigation = round((armour_class / 10) * 3.15)
    return base_damage - mitigation


def _resolve_enchant_level(item: Any, payload: Mapping[str, Any]) -> int:
    if "enchant_level" in payload:
        return max(0, _coerce_int(payload.get("enchant_level"), 0))

    instance_id = _resolve_instance_id(payload)
    if instance_id:
        return max(0, itemsreg.get_enchant_level(instance_id))

    if isinstance(item, str) and item:
        return max(0, itemsreg.get_enchant_level(item))

    return 0


def get_total_ac(defender_state: Any) -> int:
    """Return the defender's total armour class.

    Parameters
    ----------
    defender_state
        Mapping or object describing the defender. May contain precomputed armour values
        or references to equipped armour.

    Returns
    -------
    int
        Armour class including dexterity and armour bonuses. Values are clamped to be
        non-negative.
    """

    ac = combat_calc.armour_class_for_active(defender_state)
    return max(0, _coerce_int(ac, 0))


def _resolve_item_payload(item: Any) -> MutableMapping[str, Any]:
    if isinstance(item, str) and item:
        inst = itemsreg.get_instance(item)
        if isinstance(inst, Mapping):
            return dict(inst)
        return {"item_id": item}
    return _normalize_mapping(item)


def _resolve_attacker_strength(attacker_state: Any) -> int:
    if isinstance(attacker_state, Mapping):
        derived = attacker_state.get("derived") if isinstance(attacker_state.get("derived"), Mapping) else None
        if isinstance(derived, Mapping) and derived.get("str_bonus") is not None:
            return max(0, _coerce_int(derived.get("str_bonus"), 0))

        stats_block = attacker_state.get("stats") if isinstance(attacker_state.get("stats"), Mapping) else None
        if isinstance(stats_block, Mapping) and stats_block.get("str") is not None:
            strength = _coerce_int(stats_block.get("str"), 0)
            return max(0, strength // 10)

    stats = pstate.get_stats_for_active(attacker_state)
    strength = _coerce_int(stats.get("str"), 0)
    return max(0, strength // 10)


def _resolve_attack_context(
    item: Any,
    attacker_state: Any,
    *,
    source: Optional[str] = None,
) -> _AttackContext:
    payload = _resolve_item_payload(item)
    template = _resolve_item_template(payload)
    attack_source = _resolve_attack_source(payload, template, hint=source)
    base_power = _resolve_base_power(payload, template, source=attack_source)
    enchant_level = _resolve_enchant_level(item, payload)
    strength_bonus = _resolve_attacker_strength(attacker_state)
    return _AttackContext(
        payload=payload,
        template=template,
        source=attack_source,
        base_power=base_power,
        enchant_level=enchant_level,
        strength_bonus=strength_bonus,
    )


def get_attacker_power(item: Any, attacker_state: Any, *, source: Optional[str] = None) -> int:
    """Return the attacker's raw power before mitigation.

    Parameters
    ----------
    item
        Instance ID or mapping describing the weapon being used.
    attacker_state
        Mapping describing the attacking entity. Strength bonuses are resolved from this
        payload.
    source
        Optional hint forcing ``"melee"``, ``"bolt"``, or ``"innate"`` damage sources.

    Returns
    -------
    int
        Base power plus enchantment and strength contributions.
    """

    context = _resolve_attack_context(item, attacker_state, source=source)
    return context.base_power + (4 * context.enchant_level) + context.strength_bonus


class AttackResult:
    """Result bundle describing an attack prior to floors."""

    __slots__ = ("damage", "source")

    def __init__(self, damage: int, source: str) -> None:
        self.damage = damage
        self.source = source


def resolve_attack(
    item: Any,
    attacker_state: Any,
    defender_state: Any,
    *,
    source: Optional[str] = None,
) -> AttackResult:
    """Return the raw attack outcome prior to minimum damage floors.

    Parameters
    ----------
    item
        Instance ID or mapping representing the weapon or innate attack payload.
    attacker_state
        Mapping describing the attacker.
    defender_state
        Mapping describing the defender.
    source
        Optional hint overriding source detection.

    Returns
    -------
    AttackResult
        ``damage`` is the pre-floor value after subtracting defender AC. ``source`` is the
        resolved attack source.
    """

    context = _resolve_attack_context(item, attacker_state, source=source)
    attack_power = context.base_power + (4 * context.enchant_level) + context.strength_bonus
    defender_ac = get_total_ac(defender_state)
    damage = apply_ac_mitigation(attack_power, defender_ac)
    return AttackResult(damage=damage, source=context.source)


def compute_base_damage(item: Any, attacker_state: Any, defender_state: Any) -> int:
    """Return the mitigated damage prior to applying damage floors."""

    return resolve_attack(item, attacker_state, defender_state).damage


def wake_target_if_asleep(ctx: Any, target: Any) -> bool:
    """Wake ``target`` if it is currently asleep.

    Returns ``True`` when the target was asleep and has been marked awake.
    """

    from mutants.services.monster_ai import wake as wake_mod

    try:
        status = wake_mod.monster_status(target)
    except Exception:
        return False

    if status != wake_mod.MonsterStatus.ASLEEP:
        return False

    return wake_mod.wake_monster(ctx, target, reason="damage")

