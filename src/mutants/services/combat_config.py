"""Combat configuration loader and defaults.

The configuration centralises the numerical knobs that drive combat and
monster AI behaviour. Values are drawn from :mod:`docs/monster_ai_spec` and
may be overridden at runtime via ``state/config/combat.json``.  Downstream
systems can import :func:`load_combat_config` from
``mutants.services.combat_config`` to access a frozen dataclass of settings
along with the resolved override path.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, fields as dataclass_fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Mapping

LOG = logging.getLogger(__name__)

_CONFIG_SUBDIR = "config"
_CONFIG_FILENAME = "combat.json"

_HEAL_COST_MULTIPLIER_BASE = {
    "warrior": 750,
    "priest": 750,
    "mage": 1_200,
    "wizard": 1_000,
    "thief": 200,
    "default": 200,
}


def _default_heal_cost_multiplier() -> Mapping[str, int]:
    return MappingProxyType(dict(_HEAL_COST_MULTIPLIER_BASE))


def _freeze_heal_cost_multiplier(values: Mapping[str, int]) -> Mapping[str, int]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class CombatRNGSeeds:
    """Seed overrides for deterministic combat simulations."""

    wake: int | None = None
    gates: int | None = None
    loot: int | None = None


@dataclass(frozen=True)
class CombatConfig:
    """Container for combat configuration knobs."""

    wake_on_look: int = 30
    wake_on_entry: int = 50
    flee_hp_pct: int = 25
    flee_pct: int = 20
    heal_at_pct: int = 85
    heal_pct: int = 45
    heal_cost: int = 150
    convert_pct: int = 30
    low_ion_pct: int = 70
    cast_pct: int = 1
    attack_pct: int = 45
    pickup_pct: int = 25
    emote_pct: int = 8
    spell_cost: int = 8
    spell_success_pct: int = 75
    cracked_pickup_bonus: int = 10
    cracked_flee_bonus: int = 5
    post_kill_force_pickup_pct: int = 25
    heal_cost_multiplier: Mapping[str, int] = field(
        default_factory=_default_heal_cost_multiplier
    )
    rng_seeds: CombatRNGSeeds = field(default_factory=CombatRNGSeeds)
    override_path: Path | None = None


__all__ = ["CombatConfig", "CombatRNGSeeds", "load_combat_config"]

_DEFAULT_CONFIG = CombatConfig()
_INT_FIELDS = {
    f.name
    for f in dataclass_fields(CombatConfig)
    if f.init and f.name not in {"rng_seeds", "override_path", "heal_cost_multiplier"}
}


def load_combat_config(*, state_dir: str) -> CombatConfig:
    """Load combat configuration overrides from ``state/config/combat.json``.

    Parameters
    ----------
    state_dir:
        Base directory that holds the persistent ``state`` tree.

    Returns
    -------
    CombatConfig
        Frozen dataclass with defaults merged with any JSON overrides.
        ``override_path`` always points at the expected JSON file, even when
        no overrides are present.
    """

    root = Path(state_dir)
    override_path = root / _CONFIG_SUBDIR / _CONFIG_FILENAME
    overrides = _load_overrides(override_path)

    config = _DEFAULT_CONFIG
    if overrides:
        config = replace(config, **overrides)
        LOG.info(
            "combat config overrides applied from %s: %s",
            override_path,
            ", ".join(sorted(overrides)),
        )

    return replace(config, override_path=override_path)


def _load_overrides(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        LOG.warning("combat config override unreadable: %s", path, exc_info=True)
        return {}

    if not isinstance(raw, Mapping):
        LOG.warning("combat config override must be a mapping: %s", path)
        return {}

    overrides: Dict[str, Any] = {}

    for field_name in _INT_FIELDS:
        if field_name not in raw:
            continue
        value = raw[field_name]
        try:
            overrides[field_name] = int(value)
        except (TypeError, ValueError):
            LOG.warning(
                "combat config override for %s is not an int: %r", field_name, value
            )

    if "rng_seeds" in raw:
        parsed_seeds = _parse_rng_seeds(raw["rng_seeds"])
        if parsed_seeds is not None:
            overrides["rng_seeds"] = parsed_seeds

    heal_multiplier_overrides = _parse_heal_cost_multiplier_overrides(raw)
    if heal_multiplier_overrides is not None:
        overrides["heal_cost_multiplier"] = heal_multiplier_overrides

    recognized_keys = set(overrides)
    recognized_keys.add("rng_seeds")
    recognized_keys.update(
        key
        for key in raw
        if isinstance(key, str) and key.startswith("heal_cost_multiplier.")
    )

    unused = sorted(set(raw) - recognized_keys)
    if unused:
        LOG.debug("combat config override ignored keys: %s", ", ".join(unused))

    return overrides


def _parse_heal_cost_multiplier_overrides(raw: Mapping[str, Any]) -> Mapping[str, int] | None:
    overrides: Dict[str, Any] = {}

    direct = raw.get("heal_cost_multiplier")
    if direct is not None:
        if isinstance(direct, Mapping):
            overrides.update(direct.items())
        else:
            LOG.warning(
                "combat config heal_cost_multiplier override must be a mapping: %r",
                direct,
            )

    prefix = "heal_cost_multiplier."
    for key, value in raw.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        klass = key[len(prefix) :]
        if not klass:
            LOG.warning(
                "combat config heal_cost_multiplier override has empty class key: %r",
                key,
            )
            continue
        overrides[klass] = value

    if not overrides:
        return None

    merged: Dict[str, int] = dict(_HEAL_COST_MULTIPLIER_BASE)
    applied = False

    for klass, value in overrides.items():
        normalized = str(klass).strip().lower()
        if not normalized:
            LOG.warning(
                "combat config heal_cost_multiplier override has empty class key: %r",
                klass,
            )
            continue
        try:
            merged[normalized] = int(value)
        except (TypeError, ValueError):
            LOG.warning(
                "combat config heal_cost_multiplier override for %s is not an int: %r",
                normalized,
                value,
            )
            continue
        applied = True

    if not applied:
        return None

    return _freeze_heal_cost_multiplier(merged)


def _parse_rng_seeds(raw: Any) -> CombatRNGSeeds | None:
    if raw is None:
        return CombatRNGSeeds()
    if not isinstance(raw, Mapping):
        LOG.warning("combat config rng_seeds override must be a mapping: %r", raw)
        return None

    seeds: Dict[str, int | None] = {}
    for field in dataclass_fields(CombatRNGSeeds):
        if field.name not in raw:
            continue
        value = raw[field.name]
        if value is None:
            seeds[field.name] = None
            continue
        try:
            seeds[field.name] = int(value)
        except (TypeError, ValueError):
            LOG.warning(
                "combat config rng_seeds override for %s is not an int: %r",
                field.name,
                value,
            )

    return CombatRNGSeeds(**seeds)

