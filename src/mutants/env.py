from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

from mutants.state import state_path

_LOG = logging.getLogger(__name__)

_STATE_BACKEND_ENV: Final[str] = "MUTANTS_STATE_BACKEND"
_VALID_STATE_BACKENDS: Final[frozenset[str]] = frozenset({"json", "sqlite"})
_DB_FILENAME: Final[str] = "mutants.db"
_CONFIG_LOGGED = False


def get_state_backend() -> str:
    """Return the configured state backend.

    The backend is controlled via the ``MUTANTS_STATE_BACKEND`` environment
    variable. Only the ``"json"`` and ``"sqlite"`` values are recognised at the
    moment; any other value falls back to ``"json"``.
    """

    raw = os.getenv(_STATE_BACKEND_ENV, "json")
    if raw is None:
        backend = "json"
    else:
        candidate = raw.strip().lower()
        backend = candidate if candidate in _VALID_STATE_BACKENDS else "json"

    _log_configuration_once(backend)
    return backend


def get_state_database_path() -> Path:
    """Return the resolved path to the SQLite state database file."""

    return state_path(_DB_FILENAME)


def _log_configuration_once(backend: str) -> None:
    global _CONFIG_LOGGED

    if _CONFIG_LOGGED:
        return

    _LOG.info("state backend=%s db_path=%s", backend, get_state_database_path())
    _CONFIG_LOGGED = True
