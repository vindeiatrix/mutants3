from __future__ import annotations

"""Development-time content validations for catalog and state files."""

import json
import logging
import os
from typing import Any, Dict, List, Tuple

from mutants import state
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

    try:
        _validate_player_targets(summary, strict=strict)
    except ValueError:
        # Re-raise after logging context so callers can surface the failure.
        LOG.error("player target validation failed", exc_info=True)
        raise

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

def _is_string_or_none(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _iter_target_maps(payload: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    mappings: List[Tuple[str, Dict[str, Any]]] = []
    root_map = payload.get("target_monster_id_by_class")
    if isinstance(root_map, dict):
        mappings.append(("target_monster_id_by_class", root_map))

    active = payload.get("active")
    if isinstance(active, dict):
        active_map = active.get("target_monster_id_by_class")
        if isinstance(active_map, dict):
            mappings.append(("active.target_monster_id_by_class", active_map))

    players = payload.get("players")
    if isinstance(players, list):
        for idx, player in enumerate(players):
            if not isinstance(player, dict):
                continue
            player_map = player.get("target_monster_id_by_class")
            if isinstance(player_map, dict):
                mappings.append((f"players[{idx}].target_monster_id_by_class", player_map))
    return mappings


def _validate_player_targets(summary: Dict[str, Any], *, strict: bool) -> None:
    details: Dict[str, Any] = {"checked": 0, "invalid": []}
    path = state.state_path("playerlivestate.json")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        details["status"] = "missing"
        summary["player_targets"] = details
        return
    except OSError as exc:
        details["status"] = f"error:{exc.__class__.__name__}"
        details["message"] = str(exc)
        summary["player_targets"] = details
        if strict:
            raise
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        details["status"] = "invalid-json"
        details["message"] = str(exc)
        summary["player_targets"] = details
        if strict:
            raise
        return

    invalid: List[Dict[str, Any]] = []
    for path_label, mapping in _iter_target_maps(payload):
        for key, value in mapping.items():
            details["checked"] += 1
            if not _is_string_or_none(value):
                invalid.append({"path": f"{path_label}.{key}", "value": value})

    details["invalid"] = invalid
    summary["player_targets"] = details

    if invalid and strict:
        raise ValueError(
            "target_monster_id_by_class entries must be string or null: "
            + ", ".join(entry["path"] for entry in invalid)
        )

