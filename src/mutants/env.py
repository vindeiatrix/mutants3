from __future__ import annotations

import os
from typing import Final

_VALID_STATE_BACKENDS: Final[frozenset[str]] = frozenset({"json", "sqlite"})


def get_state_backend() -> str:
    """Return the configured state backend.

    The backend is controlled via the ``MUTANTS_STATE_BACKEND`` environment
    variable. Only the ``"json"`` and ``"sqlite"`` values are recognised at the
    moment; any other value falls back to ``"json"``.
    """

    raw = os.getenv("MUTANTS_STATE_BACKEND", "json")
    if raw is None:
        return "json"
    backend = raw.strip().lower()
    if backend in _VALID_STATE_BACKENDS:
        return backend
    return "json"
