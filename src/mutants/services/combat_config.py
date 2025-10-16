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
from typing import Any, Dict, Mapping

LOG = logging.getLogger(__name__)

_CONFIG_SUBDIR = "config"
_CONFIG_FILENAME = "combat.json"


@dataclass(frozen=True)
class CombatRNGSeeds:
    """Seed overrides for deterministic combat simulations."""

    wake: int | None = None
    gates: int | None = None
    loot: int | None = None


@dataclass(frozen=True)
class CombatConfig:
    """Container for combat configuration knobs."""

    wake_on_look: int = 15
    wake_on_entry: int = 10
    flee_hp_pct: int = 25
    flee_pct: int = 10
    heal_at_pct: int = 80
    heal_pct: int = 20
    heal_cost: int = 5
    convert_pct: int = 20
    low_ion_pct: int = 50
    cast_pct: int = 25
    attack_pct: int = 35
    pickup_pct: int = 15
    emote_pct: int = 10
    spell_cost: int = 10
    spell_success_pct: int = 75
    cracked_pickup_bonus: int = 10
    cracked_flee_bonus: int = 5
    rng_seeds: CombatRNGSeeds = field(default_factory=CombatRNGSeeds)
    override_path: Path | None = None


__all__ = ["CombatConfig", "CombatRNGSeeds", "load_combat_config"]

_DEFAULT_CONFIG = CombatConfig()
_INT_FIELDS = {
    f.name
    for f in dataclass_fields(CombatConfig)
    if f.init and f.name not in {"rng_seeds", "override_path"}
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

    unused = sorted(set(raw) - set(overrides) - {"rng_seeds"})
    if unused:
        LOG.debug("combat config override ignored keys: %s", ", ".join(unused))

    return overrides


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
