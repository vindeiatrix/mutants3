from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from time import time
from typing import Any, Dict, Iterable, Optional, Sequence

from mutants.state import default_repo_state

__all__ = ["SQLiteConnectionManager", "SQLiteItemsInstanceStore"]



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
        conn.row_factory = sqlite3.Row
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


class SQLiteItemsInstanceStore:
    """SQLite-backed implementation of :class:`ItemsInstanceStore`."""

    __slots__ = ("_manager",)

    _COLUMNS: Sequence[str] = (
        "iid",
        "item_id",
        "year",
        "x",
        "y",
        "owner",
        "enchant",
        "condition",
        "origin",
        "drop_source",
        "created_at",
    )

    def __init__(self, manager: SQLiteConnectionManager) -> None:
        self._manager = manager

    def _connection(self) -> sqlite3.Connection:
        return self._manager.connect()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {key: row[key] for key in self._COLUMNS}

    def get_by_iid(self, iid: str) -> Optional[Dict[str, Any]]:
        conn = self._connection()
        cur = conn.execute(
            "SELECT iid, item_id, year, x, y, owner, enchant, condition, origin, drop_source, created_at "
            "FROM items_instances WHERE iid = ?",
            (str(iid),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        conn = self._connection()
        cur = conn.execute(
            "SELECT iid, item_id, year, x, y, owner, enchant, condition, origin, drop_source, created_at "
            "FROM items_instances WHERE year = ? AND x = ? AND y = ? "
            "ORDER BY created_at ASC, iid ASC",
            (year, x, y),
        )
        return [self._row_to_dict(row) for row in cur.fetchall()]

    def list_by_owner(self, owner: str) -> Iterable[Dict[str, Any]]:
        conn = self._connection()
        cur = conn.execute(
            "SELECT iid, item_id, year, x, y, owner, enchant, condition, origin, drop_source, created_at "
            "FROM items_instances WHERE owner = ? ORDER BY created_at ASC, iid ASC",
            (str(owner),),
        )
        return [self._row_to_dict(row) for row in cur.fetchall()]

    def mint(self, rec: Dict[str, Any]) -> None:
        payload = {key: rec.get(key) for key in self._COLUMNS}
        iid = payload["iid"]
        item_id = payload["item_id"]
        if iid is None:
            raise KeyError("iid")
        if item_id is None:
            raise KeyError("item_id")
        payload["iid"] = str(iid)
        payload["item_id"] = str(item_id)

        if payload["created_at"] is None:
            created = int(time())
            payload["created_at"] = created
            if isinstance(rec, dict):
                rec.setdefault("created_at", created)

        columns = ", ".join(self._COLUMNS)
        placeholders = ", ".join("?" for _ in self._COLUMNS)
        values = tuple(payload[key] for key in self._COLUMNS)

        conn = self._connection()
        try:
            with conn:
                conn.execute(
                    f"INSERT INTO items_instances ({columns}) VALUES ({placeholders})",
                    values,
                )
        except sqlite3.IntegrityError as exc:  # duplicate iid or other constraint failure
            raise KeyError(str(iid)) from exc

    def move(self, iid: str, *, year: int, x: int, y: int) -> None:
        self.update_fields(str(iid), year=year, x=x, y=y)

    def update_fields(self, iid: str, **fields: Any) -> None:
        if not fields:
            return
        updates = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in self._COLUMNS or key == "iid":
                raise KeyError(key)
            updates.append(f"{key} = ?")
            values.append(value)
        values.append(str(iid))

        conn = self._connection()
        with conn:
            cur = conn.execute(
                f"UPDATE items_instances SET {', '.join(updates)} WHERE iid = ?",
                values,
            )
            if cur.rowcount == 0:
                raise KeyError(str(iid))

    def delete(self, iid: str) -> None:
        conn = self._connection()
        with conn:
            cur = conn.execute(
                "DELETE FROM items_instances WHERE iid = ?",
                (str(iid),),
            )
            if cur.rowcount == 0:
                raise KeyError(str(iid))
