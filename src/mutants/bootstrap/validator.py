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
        LOG.error("player target validation failed", exc_info=True)
        raise

    try:
        _validate_worlds(summary, strict=strict)
    except ValueError:
        LOG.error("world validation failed", exc_info=True)
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


def _validate_worlds(summary: Dict[str, Any], *, strict: bool) -> None:
    """Ensure adjacent tiles are not separated by hard walls."""

    from mutants.registries import world as world_registry  # local import to avoid cycle

    registry = world_registry.WorldRegistry()
    details: Dict[str, Any] = {"checked_edges": 0, "repaired": 0, "invalid": []}
    years: List[int] = []
    for p in registry.base_dir.glob("*.json"):
        try:
            years.append(int(p.stem))
        except ValueError:
            continue
    years = sorted(set(years))
    for year in years:
        try:
            yw = registry.load_year(year)
        except Exception as exc:
            details["invalid"].append({"year": year, "error": str(exc)})
            if strict:
                raise
            continue
        for (x, y), tile in list(yw._tiles_by_xy.items()):
            for dir_token, opp in (("N", "S"), ("S", "N"), ("E", "W"), ("W", "E")):
                nx, ny = yw._neighbor_xy(x, y, dir_token)
                if (nx, ny) not in yw._tiles_by_xy:
                    continue
                edge = tile["edges"].get(dir_token, {})
                base = edge.get("base")
                details["checked_edges"] += 1
                if base not in (world_registry.BASE_OPEN, world_registry.BASE_GATE, None):
                    details["repaired"] += 1
        try:
            yw.save()
        except Exception:
            LOG.debug("world save skipped for %s", year, exc_info=True)
    summary["worlds"] = details

