#!/usr/bin/env python3
"""Bootstrap helpers for loading the monsters catalog and initial spawn."""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mutants.state import state_path
from mutants.registries.sqlite_store import SQLiteConnectionManager, get_stores
from mutants.registries.monsters_catalog import load_monsters_catalog
from mutants.registries import items_instances as items_instances

PASSABLE_TILE_LIMIT = 8
PASSABLE_TILE_MIN = 4
DEFAULT_SEED = 0xC0FFEE


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cur.fetchone()[0])


def _load_catalog_payload(catalog_path: Path) -> List[Dict[str, object]]:
    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalog JSON not found: {catalog_path}")
    with catalog_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("Catalog JSON must be a list of objects")
    payload: List[Dict[str, object]] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("Catalog JSON entries must be objects")
        monster_id = entry.get("monster_id")
        if not monster_id:
            raise ValueError("Catalog entries must include 'monster_id'")
        payload.append(dict(entry))
    return payload


def _import_catalog(conn: sqlite3.Connection, catalog_path: Path) -> int:
    payload = _load_catalog_payload(catalog_path)
    if not payload:
        return 0

    records: List[Tuple[str, str]] = []
    for entry in payload:
        monster_id = str(entry["monster_id"])
        data_json = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        records.append((monster_id, data_json))

    sql = (
        "INSERT INTO monsters_catalog (monster_id, data_json) "
        "VALUES (?, ?) "
        "ON CONFLICT(monster_id) DO UPDATE SET data_json = excluded.data_json"
    )

    with conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(sql, records)
    return len(records)


def _collect_tiles_for_year(year: int) -> List[Tuple[int, int]]:
    world_path = state_path("world", f"{int(year)}.json")
    coords: List[Tuple[int, int]] = []
    try:
        with world_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return coords

    tiles = data.get("tiles") or data.get("grid") or []
    if isinstance(tiles, Sequence):
        for tile in tiles:
            if not isinstance(tile, Mapping):
                continue
            pos = tile.get("pos")
            if isinstance(pos, Sequence) and len(pos) >= 3:
                try:
                    coords.append((int(pos[1]), int(pos[2])))
                except (TypeError, ValueError):
                    continue
    return coords


def _spawn_years(entry: Mapping[str, object]) -> List[int]:
    years_raw = entry.get("spawn_years")
    if not isinstance(years_raw, (list, tuple)):
        return []
    cleaned: List[int] = []
    for value in years_raw:
        try:
            cleaned.append(int(value))
        except (TypeError, ValueError):
            continue
    if len(cleaned) == 2 and cleaned[0] <= cleaned[1]:
        return list(range(cleaned[0], cleaned[1] + 1))
    return sorted(set(cleaned))


def _rand_between(rng: random.Random, a: int, b: int) -> int:
    low = min(int(a), int(b))
    high = max(int(a), int(b))
    return rng.randint(low, high)


def _mint_item_records(
    items_store,
    monster_id: str,
    pos: Tuple[int, int, int],
    item_ids: Iterable[str],
    *,
    created_at: int,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    bag_entries: List[Dict[str, object]] = []
    inventory_entries: List[Dict[str, object]] = []
    store_records: List[Dict[str, object]] = []
    year, x, y = pos
    for raw in item_ids:
        if not raw:
            continue
        iid = items_instances.mint_iid()
        record = {
            "iid": iid,
            "item_id": str(raw),
            "year": int(year),
            "x": int(x),
            "y": int(y),
            "owner": monster_id,
            "enchant": 0,
            "condition": 100,
            "charges": 0,
            "origin": "monster_spawn",
            "drop_source": None,
            "created_at": created_at,
        }
        store_records.append(record)
        bag_entries.append({
            "item_id": str(raw),
            "iid": iid,
            "origin": "monster_spawn",
            "condition": 100,
            "enchant_level": 0,
        })
        inventory_entries.append({
            "item_id": str(raw),
            "instance_id": iid,
        })
    return bag_entries, inventory_entries, store_records


def _spawn_instances(
    manager: SQLiteConnectionManager,
    *,
    seed: int,
) -> Tuple[int, int]:
    catalog = load_monsters_catalog(manager.path)
    spawnable = catalog.list_spawnable()
    if not spawnable:
        return (0, 0)

    stores = get_stores(manager.path)
    monsters_store = stores.monsters
    items_store = stores.items

    rng = random.Random(seed)
    occupancy: Dict[int, set[Tuple[int, int]]] = {}
    total_spawned = 0
    total_items = 0

    for entry in spawnable:
        years = _spawn_years(entry)
        if not years:
            continue
        for year in years:
            tiles = _collect_tiles_for_year(year)
            if not tiles:
                continue
            used = occupancy.setdefault(int(year), set())
            available = [pos for pos in tiles if (pos[0], pos[1]) not in used]
            if not available:
                continue
            local_rng = random.Random(f"{entry['monster_id']}:{year}:{seed}")
            desired = local_rng.randint(PASSABLE_TILE_MIN, PASSABLE_TILE_LIMIT)
            local_rng.shuffle(available)
            picks = available[:desired]
            for x, y in picks:
                instance_id = f"{entry['monster_id']}#{uuid.uuid4().hex[:8]}"
                hp_max = int(entry.get("hp_max", 1))
                pos = (int(year), int(x), int(y))
                created_at = int(time.time() * 1000)

                starter_items_raw = entry.get("starter_items", [])
                starter_items: List[str] = []
                if isinstance(starter_items_raw, (list, tuple)):
                    for token in starter_items_raw:
                        if isinstance(token, (str, int)):
                            starter_items.append(str(token))
                starter_items = starter_items[:4]

                armour_raw = entry.get("starter_armour")
                armour_ids: List[str] = []
                if isinstance(armour_raw, (list, tuple)):
                    armour_ids = [str(a) for a in armour_raw if isinstance(a, (str, int))]
                elif isinstance(armour_raw, (str, int)):
                    armour_ids = [str(armour_raw)] if str(armour_raw) else []

                bag_entries, inventory_entries, item_records = _mint_item_records(
                    items_store,
                    instance_id,
                    pos,
                    starter_items,
                    created_at=created_at,
                )
                armour_entries, armour_inventory, armour_records = _mint_item_records(
                    items_store,
                    instance_id,
                    pos,
                    armour_ids,
                    created_at=created_at,
                )
                total_items += len(item_records) + len(armour_records)

                armour_slot: Optional[Dict[str, object]] = None
                if armour_entries:
                    armour_slot = dict(armour_entries[0])
                    bag_entries.extend(armour_entries)
                inventory_payload = (inventory_entries + armour_inventory)[:4]

                wielded: Optional[str] = None
                if bag_entries:
                    wielded = bag_entries[0].get("iid")

                ions_val = _rand_between(rng, entry.get("ions_min", 0), entry.get("ions_max", 0))
                riblets_val = _rand_between(rng, entry.get("riblets_min", 0), entry.get("riblets_max", 0))

                record = {
                    "instance_id": instance_id,
                    "monster_id": entry.get("monster_id"),
                    "name": entry.get("name"),
                    "stats": entry.get("stats"),
                    "pos": [pos[0], pos[1], pos[2]],
                    "hp": {"current": hp_max, "max": hp_max},
                    "armour_class": int(entry.get("armour_class", 0)),
                    "level": int(entry.get("level", 1)),
                    "ions": int(ions_val),
                    "riblets": int(riblets_val),
                    "inventory": inventory_payload,
                    "bag": bag_entries,
                    "armour_slot": armour_slot,
                    "wielded": wielded,
                    "readied_spell": None,
                    "target_player_id": None,
                    "target_monster_id": None,
                    "ready_target": None,
                    "taunt": entry.get("taunt", ""),
                    "innate_attack": entry.get("innate_attack", {}),
                    "spells": list(entry.get("spells", [])),
                    "pinned_years": years,
                    "origin": "initial_spawn",
                    "created_at": created_at,
                }

                monsters_store.spawn(record)
                for payload in item_records + armour_records:
                    items_store.mint(payload)
                used.add((x, y))
                total_spawned += 1
    return total_spawned, total_items


def ensure_monsters(manager: SQLiteConnectionManager, catalog_path: Path, *, seed: int = DEFAULT_SEED) -> None:
    conn = manager.connect()
    catalog_rows = _table_count(conn, "monsters_catalog")
    if catalog_rows == 0:
        imported = _import_catalog(conn, catalog_path)
        print(f"Monsters catalog imported: {imported}")
    else:
        print(f"Monsters catalog present (rows: {catalog_rows}).")

    instance_rows = _table_count(conn, "monsters_instances")
    if instance_rows == 0:
        spawned, items = _spawn_instances(manager, seed=seed)
        print(f"Initial monster spawn complete: {spawned} monsters, {items} items minted.")
    else:
        print(f"Monsters already present (rows: {instance_rows}).")


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        "-d",
        metavar="PATH",
        help="Optional path to the SQLite database file (defaults to project state database).",
    )
    parser.add_argument(
        "--catalog",
        metavar="PATH",
        default=str(state_path("monsters", "catalog.json")),
        help="Path to the monsters catalog JSON file.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Deterministic seed used when selecting spawn positions.",
    )
    args = parser.parse_args(argv)

    manager = SQLiteConnectionManager(args.database)
    ensure_monsters(manager, Path(args.catalog), seed=args.seed)


if __name__ == "__main__":
    main()
