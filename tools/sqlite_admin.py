#!/usr/bin/env python3
"""Lightweight administration CLI for the SQLite state database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Callable

# Ensure the project source tree is importable when executed directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mutants.registries.sqlite_store import SQLiteConnectionManager  # noqa: E402


def _build_manager(db_path: str | None) -> SQLiteConnectionManager:
    """Return a connection manager for the provided database path."""

    if db_path is not None:
        return SQLiteConnectionManager(db_path)
    return SQLiteConnectionManager()


def _with_connection(
    args: argparse.Namespace, action: Callable[[sqlite3.Connection, SQLiteConnectionManager], None]
) -> None:
    manager = _build_manager(args.database)
    conn = manager.connect()
    try:
        action(conn, manager)
    finally:
        manager.close()


def _command_init(args: argparse.Namespace) -> None:
    """Initialise the SQLite database schema (idempotent)."""

    def ensure_schema(conn: sqlite3.Connection, manager: SQLiteConnectionManager) -> None:
        # ``connect`` already ensures the schema; we just synchronise and report the path.
        conn.execute("SELECT 1")
        print(f"Schema ensured at {manager.path}")

    _with_connection(args, ensure_schema)


def _command_stats(args: argparse.Namespace) -> None:
    """Print item and monster instance counts."""

    def render_stats(conn: sqlite3.Connection, manager: SQLiteConnectionManager) -> None:
        cur = conn.execute("SELECT COUNT(*) FROM items_instances")
        items = int(cur.fetchone()[0])
        cur = conn.execute("SELECT COUNT(*) FROM monsters_instances")
        monsters = int(cur.fetchone()[0])
        print(f"Database: {manager.path}")
        print(f"Items instances: {items}")
        print(f"Monsters instances: {monsters}")

    _with_connection(args, render_stats)


def _command_vacuum(args: argparse.Namespace) -> None:
    """Run VACUUM and ANALYZE on the database."""

    def vacuum(conn: sqlite3.Connection, manager: SQLiteConnectionManager) -> None:
        original_isolation = conn.isolation_level
        try:
            conn.isolation_level = None
            conn.execute("VACUUM")
            conn.execute("ANALYZE")
        finally:
            conn.isolation_level = original_isolation
        print(f"Vacuumed and analysed {manager.path}")

    _with_connection(args, vacuum)


def _command_purge(args: argparse.Namespace) -> None:
    """Delete all item and monster instances from the database."""

    def purge(conn: sqlite3.Connection, manager: SQLiteConnectionManager) -> None:
        with conn:
            conn.execute("DELETE FROM items_instances")
            conn.execute("DELETE FROM monsters_instances")
        print(f"Purged instances from {manager.path}")

    _with_connection(args, purge)


def _command_catalog_import_items(args: argparse.Namespace) -> None:
    """Import the items catalog JSON into the SQLite database."""

    catalog_path = PROJECT_ROOT / "state" / "items" / "catalog.json"

    def import_catalog(conn: sqlite3.Connection, manager: SQLiteConnectionManager) -> None:
        if not catalog_path.exists():
            raise FileNotFoundError(f"Catalog JSON not found: {catalog_path}")

        with catalog_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)

        if not isinstance(payload, list):
            raise ValueError("Catalog JSON must be a list of objects")

        records: list[tuple[str, str]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                raise ValueError("Catalog JSON entries must be objects")
            item_id = entry.get("item_id")
            if not item_id:
                raise ValueError("Catalog JSON entries must include 'item_id'")
            data_json = json.dumps(entry, ensure_ascii=False, sort_keys=True)
            records.append((str(item_id), data_json))

        if not records:
            print("No items to import from catalog JSON")
            return

        sql = (
            "INSERT INTO items_catalog (item_id, data_json) "
            "VALUES (?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET data_json = excluded.data_json"
        )

        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(sql, records)

        print(f"Imported {len(records)} items into {manager.path}")

    _with_connection(args, import_catalog)


def _command_catalog_import_monsters(args: argparse.Namespace) -> None:
    """Import the monsters catalog JSON into the SQLite database."""

    catalog_path = PROJECT_ROOT / "state" / "monsters" / "catalog.json"

    def import_catalog(conn: sqlite3.Connection, manager: SQLiteConnectionManager) -> None:
        if not catalog_path.exists():
            raise FileNotFoundError(f"Catalog JSON not found: {catalog_path}")

        with catalog_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)

        if not isinstance(payload, list):
            raise ValueError("Catalog JSON must be a list of objects")

        records: list[dict[str, object]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                raise ValueError("Catalog JSON entries must be objects")
            monster_id = entry.get("monster_id")
            if not monster_id:
                raise ValueError("Catalog JSON entries must include 'monster_id'")

            record = {
                "monster_id": str(monster_id),
                "name": str(entry.get("name") or monster_id),
                "level": int(entry.get("level") or 0),
                "hp_max": int(entry.get("hp_max") or 0),
                "armour_class": int(entry.get("armour_class") or 0),
                "spawn_years": json.dumps(entry.get("spawn_years") or []),
                "spawnable": 1 if entry.get("spawnable") else 0,
                "taunt": entry.get("taunt") or "",
                "stats_json": json.dumps(entry.get("stats") or {}, ensure_ascii=False, sort_keys=True),
                "innate_attack_json": json.dumps(
                    entry.get("innate_attack") or {}, ensure_ascii=False, sort_keys=True
                ),
                "exp_bonus": entry.get("exp_bonus"),
                "ions_min": entry.get("ions_min"),
                "ions_max": entry.get("ions_max"),
                "riblets_min": entry.get("riblets_min"),
                "riblets_max": entry.get("riblets_max"),
                "spells_json": json.dumps(entry.get("spells") or []),
                "starter_armour_json": json.dumps(entry.get("starter_armour") or []),
                "starter_items_json": json.dumps(entry.get("starter_items") or []),
            }
            records.append(record)

        if not records:
            print("No monsters to import from catalog JSON")
            return

        sql = (
            "INSERT INTO monsters_catalog (monster_id, name, level, hp_max, armour_class, "
            "spawn_years, spawnable, taunt, stats_json, innate_attack_json, exp_bonus, ions_min, ions_max, "
            "riblets_min, riblets_max, spells_json, starter_armour_json, starter_items_json) "
            "VALUES (:monster_id, :name, :level, :hp_max, :armour_class, :spawn_years, :spawnable, :taunt, "
            ":stats_json, :innate_attack_json, :exp_bonus, :ions_min, :ions_max, :riblets_min, :riblets_max, :spells_json, "
            ":starter_armour_json, :starter_items_json) "
            "ON CONFLICT(monster_id) DO UPDATE SET name=excluded.name, level=excluded.level, hp_max=excluded.hp_max, "
            "armour_class=excluded.armour_class, spawn_years=excluded.spawn_years, spawnable=excluded.spawnable, "
            "taunt=excluded.taunt, stats_json=excluded.stats_json, innate_attack_json=excluded.innate_attack_json, "
            "exp_bonus=excluded.exp_bonus, ions_min=excluded.ions_min, ions_max=excluded.ions_max, "
            "riblets_min=excluded.riblets_min, riblets_max=excluded.riblets_max, spells_json=excluded.spells_json, "
            "starter_armour_json=excluded.starter_armour_json, starter_items_json=excluded.starter_items_json"
        )

        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(sql, records)

        print(f"Imported {len(records)} monsters into {manager.path}")

    _with_connection(args, import_catalog)


def _command_litter_run_now(args: argparse.Namespace) -> None:
    """Run the daily litter job immediately."""

    from mutants.bootstrap.daily_litter import run_daily_litter

    run_daily_litter()
    print("daily_litter: triggered")


def _command_litter_force_today(args: argparse.Namespace) -> None:
    """Force a rerun of daily litter for today."""

    from mutants.registries.storage import get_stores

    stores = get_stores()
    stores.items.delete_by_origin("daily_litter")
    try:
        stores.runtime_kv.delete("daily_litter_date")
    except Exception:
        pass

    from mutants.bootstrap.daily_litter import run_daily_litter

    run_daily_litter()
    print("daily_litter: forced run complete")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        "-d",
        metavar="PATH",
        help="Optional path to the SQLite database file (defaults to project state database).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Ensure the SQLite schema exists.")
    init_parser.set_defaults(func=_command_init)

    stats_parser = subparsers.add_parser("stats", help="Show counts for stored instances.")
    stats_parser.set_defaults(func=_command_stats)

    vacuum_parser = subparsers.add_parser("vacuum", help="Run VACUUM and ANALYZE on the database.")
    vacuum_parser.set_defaults(func=_command_vacuum)

    purge_parser = subparsers.add_parser("purge", help="Delete all instances while keeping catalog data.")
    purge_parser.set_defaults(func=_command_purge)

    catalog_import_items_parser = subparsers.add_parser(
        "catalog-import-items",
        help="Load the items catalog JSON into the database.",
    )
    catalog_import_items_parser.set_defaults(func=_command_catalog_import_items)

    catalog_import_monsters_parser = subparsers.add_parser(
        "catalog-import-monsters",
        help="Load the monsters catalog JSON into the database.",
    )
    catalog_import_monsters_parser.set_defaults(func=_command_catalog_import_monsters)

    litter_run_parser = subparsers.add_parser(
        "litter-run-now", help="Run daily litter immediately (idempotent)."
    )
    litter_run_parser.set_defaults(func=_command_litter_run_now)

    litter_force_parser = subparsers.add_parser(
        "litter-force-today",
        help="Force rerun of daily litter today (clears gate).",
    )
    litter_force_parser.set_defaults(func=_command_litter_force_today)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
