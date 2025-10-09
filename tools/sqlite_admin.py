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

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
