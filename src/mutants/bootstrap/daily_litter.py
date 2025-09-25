from __future__ import annotations

"""Daily litter spawn/reset system.

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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mutants.registries import items_instances
from mutants.state import STATE_ROOT


LOG = logging.getLogger(__name__)


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
        "instances": items / "instances.json",
        "rules": items / "spawn_rules.json",
        "epoch": runtime / "spawn_epoch.json",
    }

ORIGIN_FIELD = "origin"
ORIGIN_DAILY = "daily_litter"
EPOCH_FIELD = "spawn_epoch"

MAX_PER_TILE_DEFAULT = 6
DAILY_TARGET_DEFAULT = 120


# ---------------------------------------------------------------------------
# small helpers

def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _mkdir_p(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


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
    except Exception:
        pass
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# catalog / rules loading

def _load_spawn_rules(spawn_rules_path: Path) -> Dict:
    rules = _load_json(spawn_rules_path, None)
    if rules is None:
        rules = {
            "daily_target_per_year": DAILY_TARGET_DEFAULT,
            "max_ground_per_tile": MAX_PER_TILE_DEFAULT,
        }
        _mkdir_p(spawn_rules_path.parent)
        _save_json_atomic(spawn_rules_path, rules)
    return rules


def _load_spawnables_from_catalog(catalog_path: Path) -> Dict[str, Dict]:
    """Return mapping item_id -> {weight:int, cap_per_year:int|None}."""
    cat = _load_json(catalog_path, {})
    spawnables: Dict[str, Dict] = {}

    items_obj = cat.get("items", cat) if isinstance(cat, dict) else cat
    if isinstance(items_obj, dict):
        iterable = items_obj.items()
    elif isinstance(items_obj, list):
        iterable = [(x.get("id") or x.get("item_id"), x) for x in items_obj]
    else:
        iterable = []

    for item_id, meta in iterable:
        if not item_id or not isinstance(meta, dict):
            continue
        # "spawnable" must be a JSON boolean True; other truthy values are ignored
        if meta.get("spawnable") is not True:
            continue
        spawn_cfg = meta.get("spawn", {})
        weight = int(spawn_cfg.get("weight", 1))
        cap = spawn_cfg.get("cap_per_year")
        cap = int(cap) if cap is not None else None
        if weight > 0:
            spawnables[str(item_id)] = {"weight": weight, "cap_per_year": cap}
    return spawnables


# ---------------------------------------------------------------------------
# instances I/O helpers

def _load_instances_list(instances_path: Path) -> List[Dict]:
    data = _load_json(instances_path, [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("instances"), list):
            return data["instances"]
        if all(isinstance(v, dict) for v in data.values()):
            return list(data.values())
    return []


def _save_instances_list(instances_path: Path, instances: List[Dict]) -> None:
    existing = _load_json(instances_path, None)
    if isinstance(existing, dict) and isinstance(existing.get("instances"), list):
        existing["instances"] = instances
        _save_json_atomic(instances_path, existing)
    else:
        _save_json_atomic(instances_path, instances)


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
    except Exception:
        pass

    world_path = world_dir / f"{year}.json"
    data = _load_json(world_path, {})
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


def _instance_pos_key(inst: Dict) -> Optional[Tuple[int, int, int]]:
    try:
        if all(k in inst for k in ("year", "x", "y")):
            return int(inst["year"]), int(inst["x"]), int(inst["y"])
        if isinstance(inst.get("pos"), dict):
            p = inst["pos"]
            if all(k in p for k in ("year", "x", "y")):
                return int(p["year"]), int(p["x"]), int(p["y"])
    except Exception:
        return None
    return None


def _instance_item_id(inst: Dict) -> Optional[str]:
    for k in ("item_id", "catalog_id", "id"):
        v = inst.get(k)
        if isinstance(v, str):
            return v
    return None


def _remove_yesterdays_daily_litter(instances: List[Dict]) -> List[Dict]:
    return [i for i in instances if i.get(ORIGIN_FIELD) != ORIGIN_DAILY]


def _count_per_tile(instances: List[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for inst in instances:
        pos = _instance_pos_key(inst)
        if not pos:
            continue
        year, x, y = pos
        key = _tile_key(year, x, y)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _count_item_per_year(instances: List[Dict]) -> Dict[int, Dict[str, int]]:
    per_year: Dict[int, Dict[str, int]] = {}
    for inst in instances:
        pos = _instance_pos_key(inst)
        item_id = _instance_item_id(inst)
        if not pos or not item_id:
            continue
        year = pos[0]
        per_year.setdefault(year, {})
        per_year[year][item_id] = per_year[year].get(item_id, 0) + 1
    return per_year


def _new_instance_dict(item_id: str, year: int, x: int, y: int, epoch: str, seq: int) -> Dict:
    return {
        "iid": items_instances.mint_iid(),
        "item_id": item_id,
        "pos": {"year": year, "x": x, "y": y},
        "year": year,
        "x": x,
        "y": y,
        ORIGIN_FIELD: ORIGIN_DAILY,
        EPOCH_FIELD: epoch,
    }


# ---------------------------------------------------------------------------
# main entry

def run_daily_litter_reset(root: str | Path | None = None) -> None:
    paths = _paths(root)
    runtime_dir = paths["runtime"]
    epoch_path = paths["epoch"]
    log_path = paths["log"]

    _mkdir_p(runtime_dir)
    epoch = _load_json(epoch_path, {})
    today = _today_str()
    if epoch.get("last_reset") == today:
        return

    rules = _load_spawn_rules(paths["rules"])
    daily_target = int(rules.get("daily_target_per_year", DAILY_TARGET_DEFAULT))
    max_per_tile = int(rules.get("max_ground_per_tile", MAX_PER_TILE_DEFAULT))

    random.seed(today)

    instances = _load_instances_list(paths["instances"])
    instances = _remove_yesterdays_daily_litter(instances)

    per_tile = _count_per_tile(instances)
    per_year_item = _count_item_per_year(instances)

    spawnables = _load_spawnables_from_catalog(paths["catalog"])
    if not spawnables:
        LOG.info("daily_litter: no spawnable items; skipping")
        _save_instances_list(paths["instances"], instances)
        _save_json_atomic(epoch_path, {"last_reset": today})
        return

    years = _list_years(paths["world"])
    if not years:
        LOG.info("daily_litter: no world years found; skipping")
        _save_instances_list(paths["instances"], instances)
        _save_json_atomic(epoch_path, {"last_reset": today})
        return

    def build_weighted_pool(year: int) -> List[Tuple[str, int]]:
        pool: List[Tuple[str, int]] = []
        for item_id, cfg in spawnables.items():
            cap = cfg.get("cap_per_year")
            already = per_year_item.get(year, {}).get(item_id, 0)
            if cap is not None and already >= cap:
                continue
            w = int(cfg.get("weight", 1))
            if w > 0:
                pool.append((item_id, w))
        return pool

    summary: Dict[int, Dict[str, int]] = {}

    for year in years:
        tiles = _collect_open_tiles_for_year(year, paths["world"])
        if not tiles:
            LOG.warning("daily_litter: no open tiles for year %s", year)
            continue

        pool = build_weighted_pool(year)
        if not pool:
            LOG.info("daily_litter: no eligible spawnables for year %s", year)
            summary[year] = {}
            continue

        items, weights = zip(*pool)
        cumulative: List[int] = []
        s = 0
        for w in weights:
            s += w
            cumulative.append(s)
        total_weight = s

        spawned: Dict[str, int] = {}
        attempts = 0
        max_attempts = daily_target * 20
        seq = 0

        while sum(spawned.values()) < daily_target and attempts < max_attempts:
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
            already = per_year_item.get(year, {}).get(item_id, 0) + spawned.get(item_id, 0)
            if cap is not None and already >= cap:
                pool = build_weighted_pool(year)
                if not pool:
                    break
                items, weights = zip(*pool)
                cumulative = []
                s = 0
                for w in weights:
                    s += w
                    cumulative.append(s)
                total_weight = s
                continue

            x, y = tiles[random.randrange(0, len(tiles))]
            key = _tile_key(year, x, y)
            if per_tile.get(key, 0) >= max_per_tile:
                continue

            seq += 1
            inst = _new_instance_dict(item_id, year, x, y, today, seq)
            instances.append(inst)
            per_tile[key] = per_tile.get(key, 0) + 1
            spawned[item_id] = spawned.get(item_id, 0) + 1

        summary[year] = spawned

    _mkdir_p(paths["instances"].parent)
    _save_instances_list(paths["instances"], instances)
    try:
        from mutants.registries import items_instances as itemsreg

        invalidate = getattr(itemsreg, "invalidate_cache", None)
        if callable(invalidate):
            invalidate()
    except Exception:
        pass
    _mkdir_p(runtime_dir)
    _save_json_atomic(epoch_path, {"last_reset": today})

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
        except Exception:
            pass

