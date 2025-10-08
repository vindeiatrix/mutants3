from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from mutants.state import default_repo_state

__all__ = ["SQLiteConnectionManager"]


def _default_state_root() -> Path:
    """Resolve the default state root considering ``GAME_STATE_ROOT``."""

    override = os.getenv("GAME_STATE_ROOT")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    return default_repo_state()


def _resolve_db_path(db_path: Optional[os.PathLike[str] | str]) -> Path:
    if db_path is not None:
        return Path(db_path)
    return _default_state_root() / "mutants.db"


class SQLiteConnectionManager:
    """Create SQLite connections with project defaults applied."""

    __slots__ = ("_db_path", "_connection")

    def __init__(self, db_path: Optional[os.PathLike[str] | str] = None) -> None:
        self._db_path = _resolve_db_path(db_path)
        self._connection: Optional[sqlite3.Connection] = None

    @property
    def path(self) -> Path:
        return self._db_path

    def connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path)
            self._configure_connection(conn)
            self._ensure_schema(conn)
            self._connection = conn
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    version INTEGER NOT NULL
                )
                """
            )
            cur = conn.execute("SELECT COUNT(*) FROM schema_meta")
            count = cur.fetchone()[0]
            if not count:
                conn.execute("INSERT INTO schema_meta(version) VALUES (1)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS items_instances (
                    iid TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    year INT,
                    x INT,
                    y INT,
                    owner TEXT,
                    enchant INT,
                    condition INT,
                    origin TEXT,
                    drop_source TEXT,
                    created_at INT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS items_at_idx
                ON items_instances(year, x, y)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS items_owner_idx
                ON items_instances(owner)
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monsters_instances (
                    instance_id TEXT PRIMARY KEY,
                    monster_id TEXT NOT NULL,
                    year INT,
                    x INT,
                    y INT,
                    hp_cur INT,
                    hp_max INT,
                    stats_json TEXT,
                    created_at INT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS monsters_at_idx
                ON monsters_instances(year, x, y)
                """
            )
