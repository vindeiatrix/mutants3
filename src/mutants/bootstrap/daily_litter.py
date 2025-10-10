from __future__ import annotations

"""Daily litter spawn/reset system backed by the SQLite state database.

Runs once per calendar day during bootstrap:
* removes items previously spawned by this system (``origin == "daily_litter"``)
* spawns weighted items on open tiles without exceeding per-item caps or
  per-tile capacity

The module is intentionally defensive and makes a best effort if files are
missing or in unexpected shapes. All randomness is seeded by the date string so
placements remain deterministic for the day.
"""

import json
import logging
import os
import random
import sqlite3
from datetime import date, datetime
from pathlib import Path
from time import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from mutants.env import get_state_backend
from mutants.registries import items_instances, items_catalog
from mutants.registries.storage import get_stores
from mutants.registries.sqlite_store import SQLiteConnectionManager, SQLiteItemsInstanceStore
from mutants.state import STATE_ROOT


ORIGIN_DAILY = "daily_litter"

log = logging.getLogger(__name__)
LOG = log


def _paths(root: str | Path | None = None) -> Dict[str, Path]:
    """Return important runtime paths relative to ``root`` (state root by default)."""

    if root is None:
        state = STATE_ROOT
    else:
        base = Path(root)
        state = base if base.name == "state" else base / "state"
    items = state / "items"
    runtime = state / "runtime"
    world = state / "world"
    logs = state / "logs" / "game.log"
    return {
        "state": state,
        "items": items,
        "runtime": runtime,
        "world": world,
        "log": logs,
        "catalog": items / "catalog.json",
        "rules": items / "spawn_rules.json",
        "db": state / "mutants.db",
    }


ORIGIN_FIELD = "origin"
KV_LAST_RUN_KEY = "daily_litter_date"

MAX_PER_TILE_DEFAULT = 6
DAILY_TARGET_DEFAULT = 120

_ITEM_COLUMNS: Tuple[str, ...] = (
    "iid",
    "item_id",
    "year",
    "x",
    "y",
    "owner",
    "enchant",
    "condition",
    "charges",
    "origin",
    "drop_source",
    "created_at",
)


# ---------------------------------------------------------------------------
# small helpers


def _kv_get(stores, key: str):
    try:
        return stores.runtime_kv.get(key)
    except Exception:
        return None


def _kv_set(stores, key: str, value: str):
    try:
        stores.runtime_kv.set(key, value)
    except Exception:
        pass


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _mkdir_p(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, PermissionError, IsADirectoryError, json.JSONDecodeError):
        LOG.error("Failed to load JSON from %s", path, exc_info=True)
        raise


def _save_json_atomic(path: str, data) -> None:
    """Write JSON using the project atomic writer when available."""
    try:
        from ..io import atomic as atomic_io  # type: ignore
        if hasattr(atomic_io, "atomic_write_json"):
            atomic_io.atomic_write_json(path, data)  # type: ignore[attr-defined]
            return
        if hasattr(atomic_io, "write_json_atomic"):
            atomic_io.write_json_atomic(path, data)  # type: ignore[attr-defined]
            return
    except (ImportError, AttributeError):
        LOG.debug("Falling back to non-atomic JSON write for %s", path, exc_info=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# catalog / rules loading


def _load_spawn_rules(spawn_rules_path: Path) -> Dict:
    try:
        rules = _load_json(spawn_rules_path, None)
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        rules = None
    if rules is None:
        rules = {
            "daily_target_per_year": DAILY_TARGET_DEFAULT,
            "max_ground_per_tile": MAX_PER_TILE_DEFAULT,
        }
        _mkdir_p(spawn_rules_path.parent)
        _save_json_atomic(spawn_rules_path, rules)
    return rules


def _load_spawnables_from_db(manager: SQLiteConnectionManager) -> Dict[str, Dict[str, Optional[int]]]:
    """Return mapping item_id -> {weight:int, cap_per_year:int|None}."""

    spawnables: Dict[str, Dict[str, Optional[int]]] = {}
    for entry in manager.list_spawnable_items():
        if not isinstance(entry, dict) or entry.get("spawnable") is not True:
            continue
        item_id = entry.get("item_id") or entry.get("id")
        if not item_id:
            continue
        spawn_cfg_raw = entry.get("spawn")
        spawn_cfg = spawn_cfg_raw if isinstance(spawn_cfg_raw, dict) else {}
        weight = int(spawn_cfg.get("weight", 1))
        cap = spawn_cfg.get("cap_per_year")
        cap_value = int(cap) if cap is not None else None
        if weight > 0:
            spawnables[str(item_id)] = {"weight": weight, "cap_per_year": cap_value}
    return spawnables


# ---------------------------------------------------------------------------
# world helpers


def _list_years(world_dir: Path) -> List[int]:
    years: List[int] = []
    try:
        for fn in os.listdir(world_dir):
            if fn.endswith(".json"):
                years.append(int(os.path.splitext(fn)[0]))
    except FileNotFoundError:
        pass
    return sorted(years)


def _collect_open_tiles_for_year(year: int, world_dir: Path) -> List[Tuple[int, int]]:
    """
    Collect candidate tiles for ground spawns.
    World tiles store coordinates in ``tile["pos"] = [year, x, y]`` and
    movement openness is determined by edges, not a tile-level ``base``.
    We therefore simply gather coordinates for all tiles in the year.
    """
    try:
        from ..registries.world import WorldRegistry  # type: ignore
    except ImportError:
        LOG.debug("World registry unavailable; using JSON tiles for year %s", year, exc_info=True)
    else:
        try:
            w = WorldRegistry()
            coords: List[Tuple[int, int]] = []
            for meth in ("iter_tiles", "tiles"):
                if hasattr(w, meth):
                    for t in getattr(w, meth)(year):  # type: ignore[arg-type]
                        if isinstance(t, dict) and isinstance(t.get("pos"), (list, tuple)):
                            pos = t["pos"]
                            if len(pos) >= 3:
                                coords.append((int(pos[1]), int(pos[2])))
                        elif (
                            isinstance(t, tuple)
                            and len(t) >= 3
                            and isinstance(t[2], dict)
                            and isinstance(t[2].get("pos"), (list, tuple))
                        ):
                            pos = t[2]["pos"]
                            if len(pos) >= 3:
                                coords.append((int(pos[1]), int(pos[2])))
            if coords:
                return coords
        except (AttributeError, TypeError, ValueError):
            LOG.debug("Falling back to JSON tile loading for year %s", year, exc_info=True)

    world_path = world_dir / f"{year}.json"
    try:
        data = _load_json(world_path, {})
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        data = {}
    coords: List[Tuple[int, int]] = []
    tiles = data.get("tiles") or data.get("grid") or []
    if isinstance(tiles, list):
        for t in tiles:
            if isinstance(t, dict) and isinstance(t.get("pos"), (list, tuple)):
                pos = t["pos"]
                if len(pos) >= 3:
                    coords.append((int(pos[1]), int(pos[2])))
    return coords


# ---------------------------------------------------------------------------
# misc helpers


def _tile_key(year: int, x: int, y: int) -> str:
    return f"{year}:{x}:{y}"


def _fetch_per_tile_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    sql = (
        "SELECT year, x, y, COUNT(*) AS c FROM items_instances "
        "WHERE year IS NOT NULL AND x IS NOT NULL AND y IS NOT NULL "
        "GROUP BY year, x, y"
    )
    per_tile: Dict[str, int] = {}
    for row in conn.execute(sql):
        year = row["year"]
        x = row["x"]
        y = row["y"]
        count = row["c"]
        if year is None or x is None or y is None or count is None:
            continue
        key = _tile_key(int(year), int(x), int(y))
        per_tile[key] = int(count)
    return per_tile


def _fetch_per_year_item_counts(conn: sqlite3.Connection) -> Dict[int, Dict[str, int]]:
    sql = (
        "SELECT year, item_id, COUNT(*) AS c FROM items_instances "
        "WHERE year IS NOT NULL AND item_id IS NOT NULL "
        "GROUP BY year, item_id"
    )
    per_year: Dict[int, Dict[str, int]] = {}
    for row in conn.execute(sql):
        year = row["year"]
        item_id = row["item_id"]
        count = row["c"]
        if year is None or item_id is None or count is None:
            continue
        year_int = int(year)
        per_year.setdefault(year_int, {})
        per_year[year_int][str(item_id)] = int(count)
    return per_year


def _build_weighted_pool(
    year: int,
    spawnables: Dict[str, Dict[str, Optional[int]]],
    per_year_item: Dict[int, Dict[str, int]],
) -> List[Tuple[str, int]]:
    pool: List[Tuple[str, int]] = []
    counts = per_year_item.get(year, {})
    for item_id, cfg in spawnables.items():
        cap = cfg.get("cap_per_year")
        if cap is not None and counts.get(item_id, 0) >= cap:
            continue
        weight = int(cfg.get("weight", 1))
        if weight > 0:
            pool.append((item_id, weight))
    return pool


def _prepare_weight_tables(pool: Iterable[Tuple[str, int]]) -> Tuple[Tuple[str, ...], List[int], int]:
    items: List[str] = []
    cumulative: List[int] = []
    total = 0
    for item_id, weight in pool:
        items.append(item_id)
        total += int(weight)
        cumulative.append(total)
    return tuple(items), cumulative, total


def _create_spawn_record(item_id: str, year: int, x: int, y: int, created_at: int) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "iid": items_instances.mint_iid(),
        "item_id": item_id,
        "year": year,
        "x": x,
        "y": y,
        ORIGIN_FIELD: ORIGIN_DAILY,
        "enchant": 0,
        "condition": 100,
        "created_at": created_at,
    }
    try:
        defaults = items_catalog.catalog_defaults(item_id)
    except FileNotFoundError:
        defaults = {}
    charges = defaults.get("charges") if isinstance(defaults, dict) else None
    if charges is not None:
        try:
            record["charges"] = int(charges)
        except (TypeError, ValueError):
            pass
    return record


def _insert_normalized_records(
    conn: sqlite3.Connection, payloads: Iterable[Dict[str, Any]]
) -> None:
    payload_list = list(payloads)
    if not payload_list:
        return
    columns = ", ".join(_ITEM_COLUMNS)
    placeholders = ", ".join("?" for _ in _ITEM_COLUMNS)
    values = [tuple(payload.get(col) for col in _ITEM_COLUMNS) for payload in payload_list]
    conn.executemany(
        f"INSERT INTO items_instances ({columns}) VALUES ({placeholders})",
        values,
    )


# ---------------------------------------------------------------------------
# main entry


def run_daily_litter_sqlite() -> None:
    stores = get_stores()
    today = date.today().isoformat()

    icat = items_catalog

    if _kv_get(stores, KV_LAST_RUN_KEY) == today:
        log.info("daily_litter %s: already ran; skipping", today)
        return

    random.seed(today)

    try:
        spawnables: Iterable[Dict[str, Any]] = icat.list_spawnable_items()
    except Exception:
        log.exception("daily_litter_sqlite: failed to load spawnables")
        raise
    spawnables = list(spawnables)
    if not spawnables:
        log.error(
            "daily_litter %s: NO SPAWNABLE ITEMS in catalog; nothing to do", today
        )
        _kv_set(stores, KV_LAST_RUN_KEY, today)
        return

    items_store = stores.items
    items_store.delete_by_origin(ORIGIN_DAILY)

    per_year = icat.daily_target_per_year()
    years = icat.playable_years()

    total_spawned = 0
    for year in years:
        records = list(
            icat.generate_daily_litter_for_year(
                year,
                per_year,
                spawnables,
                origin=ORIGIN_DAILY,
            )
        )
        if records:
            items_store.bulk_insert(records)
            total_spawned += len(records)
        try:
            summary = icat.breakdown_summary(records)
        except Exception:
            summary = "?"
        log.info(
            "daily_litter %s year %d: spawned %d items (%s)",
            today,
            year,
            len(records),
            summary,
        )

    _kv_set(stores, KV_LAST_RUN_KEY, today)
    log.info("daily_litter %s: total spawned %d", today, total_spawned)


def run_daily_litter_reset(root: str | Path | None = None) -> None:
    paths = _paths(root)
    runtime_dir = paths["runtime"]
    log_path = paths["log"]
    rules_path = paths["rules"]
    db_path = paths["db"]

    _mkdir_p(runtime_dir)

    rules = _load_spawn_rules(rules_path)
    daily_target = int(rules.get("daily_target_per_year", DAILY_TARGET_DEFAULT))
    max_per_tile = int(rules.get("max_ground_per_tile", MAX_PER_TILE_DEFAULT))

    today = _today_str()
    random.seed(today)

    manager = SQLiteConnectionManager(db_path)
    store = SQLiteItemsInstanceStore(manager)
    spawnables = _load_spawnables_from_db(manager)
    years = _list_years(paths["world"])

    summary: Dict[int, Dict[str, int]] = {}
    normalized_records: List[Dict[str, Any]] = []
    created_base = int(time() * 1000)
    seq_counter = 0

    conn = manager.connect()
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM runtime_kv WHERE key = ?",
            (KV_LAST_RUN_KEY,),
        ).fetchone()
        if row is not None:
            value = row["value"]
            if isinstance(value, str) and value == today:
                return

        conn.execute(
            "DELETE FROM items_instances WHERE origin = ?",
            (ORIGIN_DAILY,),
        )

        per_tile = _fetch_per_tile_counts(conn)
        per_year_item = _fetch_per_year_item_counts(conn)

        if not spawnables:
            LOG.info("daily_litter: no spawnable items; skipping")
        elif not years:
            LOG.info("daily_litter: no world years found; skipping")
        else:
            for year in years:
                tiles = _collect_open_tiles_for_year(year, paths["world"])
                if not tiles:
                    LOG.warning("daily_litter: no open tiles for year %s", year)
                    continue

                pool = _build_weighted_pool(year, spawnables, per_year_item)
                items, cumulative, total_weight = _prepare_weight_tables(pool)
                if not items or total_weight <= 0:
                    LOG.info("daily_litter: no eligible spawnables for year %s", year)
                    summary[year] = {}
                    continue

                spawned: Dict[str, int] = {}
                attempts = 0
                max_attempts = daily_target * 20 if daily_target > 0 else 0

                while (
                    daily_target > 0
                    and sum(spawned.values()) < daily_target
                    and attempts < max_attempts
                ):
                    attempts += 1
                    if not items:
                        break
                    r = random.randint(1, total_weight)
                    lo, hi, pick = 0, len(cumulative) - 1, 0
                    while lo <= hi:
                        mid = (lo + hi) // 2
                        if r <= cumulative[mid]:
                            pick = mid
                            hi = mid - 1
                        else:
                            lo = mid + 1
                    item_id = items[pick]

                    cap = spawnables[item_id].get("cap_per_year")
                    already = per_year_item.get(year, {}).get(item_id, 0)
                    if cap is not None and already >= cap:
                        pool = _build_weighted_pool(year, spawnables, per_year_item)
                        items, cumulative, total_weight = _prepare_weight_tables(pool)
                        if not items or total_weight <= 0:
                            break
                        continue

                    x, y = tiles[random.randrange(0, len(tiles))]
                    key = _tile_key(year, x, y)
                    if per_tile.get(key, 0) >= max_per_tile:
                        continue

                    created_at = created_base + seq_counter
                    seq_counter += 1
                    record = _create_spawn_record(item_id, year, x, y, created_at)
                    normalized = store._normalize_record(record, created_at)
                    if normalized is None:
                        continue
                    normalized_records.append(normalized)

                    per_tile[key] = per_tile.get(key, 0) + 1
                    per_year_item.setdefault(year, {})
                    per_year_item[year][item_id] = per_year_item[year].get(item_id, 0) + 1
                    spawned[item_id] = spawned.get(item_id, 0) + 1

                summary[year] = spawned

        _insert_normalized_records(conn, normalized_records)
        conn.execute(
            "INSERT INTO runtime_kv(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (KV_LAST_RUN_KEY, today),
        )

    try:
        from mutants.registries import items_instances as itemsreg

        invalidate = getattr(itemsreg, "invalidate_cache", None)
        if callable(invalidate):
            invalidate()
    except (ImportError, AttributeError):
        LOG.debug("Failed to invalidate item registry cache", exc_info=True)

    for year, counts in summary.items():
        parts = [f"{k}\u00d7{v}" for k, v in sorted(counts.items()) if v]
        extra = f" ({', '.join(parts)})" if parts else ""
        line = f"daily_litter {today} year {year}: spawned {sum(counts.values())} items{extra}"
        LOG.info(line)
        try:
            ts = datetime.utcnow().isoformat() + "Z"
            _mkdir_p(log_path.parent)
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"{ts} SYSTEM/INFO - {line}\n")
        except (OSError, IOError):
            LOG.warning("Failed to append litter summary to %s", log_path, exc_info=True)


def run_daily_litter() -> None:
    backend = str(get_state_backend()).lower()
    if backend == "sqlite":
        return run_daily_litter_sqlite()
    from .daily_litter import run_daily_litter_reset as _json_reset

    return _json_reset()
