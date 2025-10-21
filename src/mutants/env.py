from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Final, Optional

from mutants.state import state_path
from mutants.util import parse_int

_LOG = logging.getLogger(__name__)

_STATE_BACKEND_ENV: Final[str] = "MUTANTS_STATE_BACKEND"
_VALID_STATE_BACKENDS: Final[frozenset[str]] = frozenset({"sqlite"})
_DB_FILENAME: Final[str] = "mutants.db"
_CONFIG_LOGGED = False
_COMBAT_CONFIG_FILENAME: Final[tuple[str, str]] = ("config", "combat.json")
_RNG_SEED_ENV: Final[str] = "MUTANTS_RNG_SEED"
_SPAWN_INTERVAL_ENV: Final[str] = "SPAWN_TICK_INTERVAL_TURNS"
_SPAWN_JITTER_ENV: Final[str] = "SPAWN_JITTER_PCT"
_POP_FLOOR_ENV: Final[str] = "POP_FLOOR"
_POP_CAP_ENV: Final[str] = "POP_CAP"
_SPAWN_BATCH_ENV: Final[str] = "SPAWN_BATCH_MAX"
_DEBUG_ENV: Final[str] = "DEBUG"


def _parse_bool(raw: Optional[str], *, default: bool = False) -> bool:
    if raw is None:
        return default
    token = raw.strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return default
    return value


def get_state_backend() -> str:
    """Return the configured state backend.

    The backend is controlled via the ``MUTANTS_STATE_BACKEND`` environment
    variable. Currently only the ``"sqlite"`` value is honoured; any other
    value falls back to ``"sqlite"``.
    """

    raw = os.getenv(_STATE_BACKEND_ENV)
    if raw is None:
        backend = "sqlite"
    else:
        candidate = raw.strip().lower()
        backend = candidate if candidate in _VALID_STATE_BACKENDS else "sqlite"

    _log_configuration_once(backend)
    return backend


def get_state_database_path() -> Path:
    """Return the resolved path to the SQLite state database file."""

    return state_path(_DB_FILENAME)


def get_combat_config_path() -> Path:
    """Return the resolved path to the combat configuration override file."""

    return state_path(*_COMBAT_CONFIG_FILENAME)


def get_runtime_seed() -> Optional[str]:
    """Return the configured runtime RNG seed, if provided."""

    raw = os.getenv(_RNG_SEED_ENV)
    if raw is None:
        return None

    candidate = raw.strip()
    if not candidate:
        return None

    try:
        # Normalise numeric seeds so ``42`` and ``0x2A`` resolve identically.
        return str(parse_int(candidate))
    except ValueError:
        return candidate


def _log_configuration_once(backend: str) -> None:
    global _CONFIG_LOGGED

    if _CONFIG_LOGGED:
        return

    _LOG.info(
        "state backend=%s db_path=%s combat_config=%s rng_seed=%s",
        backend,
        get_state_database_path(),
        get_combat_config_path(),
        get_runtime_seed(),
    )
    _CONFIG_LOGGED = True

def runtime_spawner_config() -> Dict[str, int]:
    """Return configuration for the runtime monster spawner."""

    interval = max(1, _parse_int_env(_SPAWN_INTERVAL_ENV, 7))
    jitter = max(0, _parse_int_env(_SPAWN_JITTER_ENV, 20))
    floor = max(0, _parse_int_env(_POP_FLOOR_ENV, 30))
    cap_default = max(floor, 60)
    cap = max(floor, _parse_int_env(_POP_CAP_ENV, cap_default))
    batch = max(1, _parse_int_env(_SPAWN_BATCH_ENV, 5))
    return {
        "interval": interval,
        "jitter_pct": jitter,
        "floor": floor,
        "cap": cap,
        "batch_max": batch,
    }


def debug_commands_enabled() -> bool:
    """Return ``True`` when debug-only commands should be enabled."""

    return _parse_bool(os.getenv(_DEBUG_ENV), default=False)
