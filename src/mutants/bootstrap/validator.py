from __future__ import annotations

"""Development-time content validations for catalog and state files."""

import logging
import os
from typing import Any, Dict

from mutants.registries import items_catalog, items_instances

LOG = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    """Return True if the environment variable ``name`` is truthy."""

    value = os.getenv(name)
    if value is None:
        return False
    token = value.strip().lower()
    return token in {"1", "true", "yes", "on"}


def should_run() -> bool:
    """Return True if validations should run for the current environment."""

    if _env_flag("MUTANTS_SKIP_VALIDATOR"):
        return False
    if _env_flag("MUTANTS_VALIDATE_CONTENT"):
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    if _env_flag("MUTANTS_DEV"):
        return True
    if _env_flag("CI"):
        return True
    return False


def run(*, strict: bool = True) -> Dict[str, Any]:
    """Execute validations and return a summary dictionary."""

    catalog = items_catalog.load_catalog()
    instances = items_instances.load_instances(strict=strict)

    summary: Dict[str, Any] = {
        "items": len(getattr(catalog, "_items_list", []) or []),
        "instances": len(instances or []),
        "strict": strict,
    }

    LOG.debug(
        "validator run complete strict=%s items=%s instances=%s",
        strict,
        summary["items"],
        summary["instances"],
    )
    return summary


def run_on_boot() -> None:
    """Run validations if the current environment warrants it."""

    if not should_run():
        return
    run(strict=True)

