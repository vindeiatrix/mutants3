#!/usr/bin/env python3
"""Apply the combat state schema migration to an existing SQLite database."""

from __future__ import annotations

import argparse
from os import PathLike
from pathlib import Path
from typing import Optional

from mutants.registries.sqlite_store import SQLiteConnectionManager


def migrate(db_path: Optional[str | PathLike[str]]) -> Path:
    """Run the schema migration for the provided database path."""

    manager = SQLiteConnectionManager(db_path)
    try:
        # Connecting ensures all migrations (including v6) are applied.
        manager.connect()
    finally:
        manager.close()
    return manager.path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help="Path to the SQLite state database. Defaults to the configured state path.",
    )
    args = parser.parse_args()
    path = migrate(args.db_path)
    print(f"Combat state schema migration applied at {path}")


if __name__ == "__main__":
    main()
