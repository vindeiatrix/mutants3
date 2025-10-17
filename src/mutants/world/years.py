"""Helpers for resolving the list of active world years."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Iterable, List, Sequence, Tuple

from mutants.engine import edge_resolver
from mutants.registries import dynamics as dynamics_registry
from mutants.registries import world as world_registry
from mutants.registries.world import DELTA as _WORLD_DELTA

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_STATE_YEARS_PATH = PROJECT_ROOT / "state" / "world" / "years.json"
_CLI_YEARS_OVERRIDE: str | Sequence[int] | None = None


def set_cli_years_override(years: str | Sequence[int] | None) -> None:
    """Set an override used when resolving world years.

    The CLI can call this once up-front to supply a comma-separated list or
    sequence of years that should take precedence over state files and catalog
    discovery.
    """

    global _CLI_YEARS_OVERRIDE
    _CLI_YEARS_OVERRIDE = years


def _dedupe_sorted(years: Iterable[int]) -> list[int]:
    unique = sorted({int(y) for y in years})
    return unique


def _parse_year_token(token: str) -> list[int]:
    token = token.strip()
    if not token:
        return []
    if "-" not in token:
        try:
            return [int(token)]
        except ValueError:
            return []
    range_part, *step_part = token.split(":", 1)
    start_str, sep, end_str = range_part.partition("-")
    if not sep:
        return []
    try:
        start = int(start_str)
        end = int(end_str)
    except ValueError:
        return []
    step = 1
    if step_part:
        try:
            step = int(step_part[0])
        except ValueError:
            step = 1
    if step == 0:
        step = 1
    if end < start:
        # Inclusive descending range support.
        step = -abs(step)
    else:
        step = abs(step)
    values: list[int] = []
    current = start
    if step > 0:
        while current <= end:
            values.append(current)
            current += step
    else:
        while current >= end:
            values.append(current)
            current += step
    return values


def _parse_years_spec(spec: str | Sequence[int]) -> list[int]:
    if isinstance(spec, str):
        tokens = spec.split(",")
        years: list[int] = []
        for token in tokens:
            years.extend(_parse_year_token(token))
        return _dedupe_sorted(years)
    try:
        return _dedupe_sorted(int(y) for y in spec)  # type: ignore[arg-type]
    except TypeError:
        return []


def _load_years_from_file() -> list[int]:
    if not _STATE_YEARS_PATH.exists():
        return []
    try:
        data = json.loads(_STATE_YEARS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    years = data.get("years") if isinstance(data, dict) else None
    if not isinstance(years, list):
        return []
    cleaned: list[int] = []
    for value in years:
        try:
            cleaned.append(int(value))
        except (TypeError, ValueError):
            continue
    return _dedupe_sorted(cleaned)


def _load_years_from_catalog(db_path: Path) -> list[int]:
    if not db_path.exists():
        return []
    years: set[int] = set()
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return []
    try:
        cursor = conn.execute("SELECT spawn_years FROM monsters_catalog")
        for (raw_years,) in cursor.fetchall():
            if not raw_years:
                continue
            try:
                parsed = json.loads(raw_years)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, list):
                for value in parsed:
                    try:
                        years.add(int(value))
                    except (TypeError, ValueError):
                        continue
    finally:
        conn.close()
    return _dedupe_sorted(years)


def find_path_between(
    year: int,
    start: Tuple[int, int],
    target: Tuple[int, int],
    *,
    world: Any | None = None,
    loader: Any | None = None,
    dynamics: Any | None = None,
    limit: int = 128,
) -> list[Tuple[int, int]]:
    """Return a simple path between ``start`` and ``target`` for ``year``."""

    start_xy = (int(start[0]), int(start[1]))
    target_xy = (int(target[0]), int(target[1]))
    if start_xy == target_xy:
        return [start_xy]

    loader_fn = loader if callable(loader) else world_registry.load_year
    dyn = dynamics if dynamics is not None else dynamics_registry

    try:
        world_obj = world if world is not None else loader_fn(year)
    except Exception:
        return []

    queue: deque[Tuple[int, int]] = deque([start_xy])
    parents: dict[Tuple[int, int], Tuple[int, int] | None] = {start_xy: None}

    while queue:
        current = queue.popleft()
        if current == target_xy:
            break
        if len(parents) > max(1, int(limit)):
            return []
        cx, cy = current
        for dir_code in ("N", "S", "E", "W"):
            delta = _WORLD_DELTA[dir_code]
            try:
                decision = edge_resolver.resolve(world_obj, dyn, int(year), cx, cy, dir_code, actor=None)
            except Exception:
                continue
            if not getattr(decision, "passable", False):
                continue
            neighbor = (cx + delta[0], cy + delta[1])
            if neighbor in parents:
                continue
            parents[neighbor] = current
            queue.append(neighbor)

    if target_xy not in parents:
        return []

    path: list[Tuple[int, int]] = []
    node: Tuple[int, int] | None = target_xy
    while node is not None:
        path.append(node)
        node = parents.get(node)
    path.reverse()
    return path


def get_world_years(db_path: str | Path) -> List[int]:
    """Return the authoritative list of world years.

    The priority order is:
    1. CLI override (if provided via :func:`set_cli_years_override`).
    2. ``state/world/years.json``.
    3. Spawn years discovered from the monsters catalog.
    """

    db_path = Path(db_path)
    if _CLI_YEARS_OVERRIDE is not None:
        parsed = _parse_years_spec(_CLI_YEARS_OVERRIDE)
        if parsed:
            return parsed
    file_years = _load_years_from_file()
    if file_years:
        return file_years
    return _load_years_from_catalog(db_path)
