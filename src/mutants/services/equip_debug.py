from __future__ import annotations

import logging
import os
from typing import Any, Optional

_LOGGER: Optional[logging.Logger] = None


def _edbg_enabled() -> bool:
    """Return True when equip-debug logging should be emitted."""

    return os.environ.get("EQUIP_DEBUG") == "1" or os.environ.get("PLAYERS_DEBUG") == "1"


def _edbg_setup_file_logging() -> logging.Logger:
    """Initialise and return the equip-debug logger."""

    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    os.makedirs(os.path.join("state", "logs"), exist_ok=True)

    logger = logging.getLogger("mutants.equipdbg")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(os.path.join("state", "logs", "equip_debug.log"))
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    _LOGGER = logger
    return logger


def _edbg_log(msg: str, **kv: Any) -> None:
    """Emit a formatted equip-debug log line when enabled."""

    if not _edbg_enabled():
        return

    logger = _edbg_setup_file_logging()

    parts = [msg]
    for key, value in kv.items():
        if value is None:
            rendered = "None"
        elif isinstance(value, (list, tuple)):
            rendered = "[" + ",".join(str(v) for v in value) + "]"
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")

    logger.info(" ".join(parts))
