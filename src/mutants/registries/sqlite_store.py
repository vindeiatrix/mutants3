from __future__ import annotations

import logging
import os
import sqlite3
import json
from pathlib import Path
from time import time
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from mutants.constants import DEFAULT_INNATE_ATTACK_LINE
from mutants.env import get_state_database_path

logger = logging.getLogger(__name__)

DEBUG_QUERY_PLAN = bool(os.getenv("MUTANTS_SQLITE_DEBUG_PLAN"))

_CATALOG_REQUIRED_FIELDS = {
    "monster_id",
    "name",
    "stats",
    "hp_max",
    "armour_class",
    "level",
    "spawn_years",
    "spawnable",
    "taunt",
    "innate_attack",
}

_CATALOG_STAT_FIELDS = {"str", "int", "wis", "dex", "con", "cha"}
_CATALOG_INNATE_FIELDS = {"name", "power_base", "power_per_level", "line"}

_MONSTER_CATALOG_COLUMNS: Tuple[str, ...] = (
    "monster_id",
    "name",
    "level",
    "hp_max",
    "armour_class",
    "spawn_years",
    "spawnable",
    "taunt",
    "stats_json",
    "innate_attack_json",
    "exp_bonus",
    "ions_min",
    "ions_max",
    "riblets_min",
    "riblets_max",
    "spells_json",
    "starter_armour_json",
    "starter_items_json",
)


def _epoch_ms() -> int:
    return int(time() * 1000)


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _begin_immediate(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")


def _normalize_created_at(value: Any, *, default: Optional[int] = None) -> int:
    base = _epoch_ms() if default is None else default
    candidate = _coerce_int(value, default=base)
    if candidate < 10_000_000_000_000:  # heuristically treat sub-ms epoch as seconds
        # Avoid overflow if the input was already in ms
        if candidate < 10_000_000_000:
            candidate *= 1000
    return candidate


def _debug_query_plan(
    conn: sqlite3.Connection, sql: str, params: Sequence[Any] | Tuple[Any, ...]
) -> None:
    if not DEBUG_QUERY_PLAN:
        return
    plan_sql = f"EXPLAIN QUERY PLAN {sql}"
    plan_rows = conn.execute(plan_sql, params).fetchall()
    for row in plan_rows:
        try:
            detail = row[3]
        except (IndexError, TypeError):
            detail = row
        logger.info("QUERY PLAN %s :: %s", sql, detail)


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_spawn_years(raw: Any, *, monster_id: str) -> list[int]:
    if isinstance(raw, (list, tuple)) and raw:
        values: list[int] = []
        for item in raw:
            try:
                values.append(int(item))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"monster {monster_id!r} spawn_years entries must be integers"
                ) from exc
        if len(values) == 2 and values[0] <= values[1]:
            return list(range(values[0], values[1] + 1))
        return sorted(dict.fromkeys(values))
    raise ValueError(f"monster {monster_id!r} spawn_years must be a non-empty list")


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, "", []):
        return []
    return [str(value)]


def _normalize_innate_attack(
    payload: Mapping[str, Any], *, monster_id: str
) -> Dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError(f"monster {monster_id!r} innate_attack name must be provided")

    line_raw = payload.get("line")
    line = str(line_raw).strip() if isinstance(line_raw, str) else ""
    if not line:
        raise ValueError(
            f"monster {monster_id!r} innate_attack line must be a non-empty string"
        )

    power_base = _coerce_int(payload.get("power_base"))
    power_per_level = _coerce_int(payload.get("power_per_level"))

    return {
        "name": name,
        "power_base": power_base,
        "power_per_level": power_per_level,
        "line": line,
    }


def _normalize_monster_catalog_entry(payload: Mapping[str, Any]) -> Dict[str, Any]:
    present = set(payload)
    missing = sorted(_CATALOG_REQUIRED_FIELDS - present)
    monster_id = str(payload.get("monster_id") or payload.get("id") or "")
    if missing:
        raise ValueError(
            f"monster {monster_id or '<unknown>'!r} missing fields: {', '.join(missing)}"
        )
    if not monster_id:
        raise ValueError("monster entry missing monster_id")

    stats = payload.get("stats")
    if not isinstance(stats, Mapping):
        raise ValueError(f"monster {monster_id!r} stats must be an object")
    missing_stats = sorted(_CATALOG_STAT_FIELDS - set(stats))
    if missing_stats:
        raise ValueError(
            f"monster {monster_id!r} stats missing: {', '.join(missing_stats)}"
        )

    innate = payload.get("innate_attack")
    if not isinstance(innate, Mapping):
        raise ValueError(f"monster {monster_id!r} innate_attack must be an object")
    missing_innate = sorted(_CATALOG_INNATE_FIELDS - set(innate))
    if missing_innate:
        raise ValueError(
            f"monster {monster_id!r} innate_attack missing: {', '.join(missing_innate)}"
        )
    innate_line = innate.get("line")
    if not isinstance(innate_line, str) or not innate_line.strip():
        raise ValueError(
            f"monster {monster_id!r} innate_attack line must be a non-empty string"
        )

    spawn_years = _normalize_spawn_years(payload.get("spawn_years"), monster_id=monster_id)

    spawnable = payload.get("spawnable")
    if isinstance(spawnable, bool):
        spawnable_flag = 1 if spawnable else 0
    elif isinstance(spawnable, (int, float)):
        spawnable_flag = 1 if int(spawnable) else 0
    else:
        raise ValueError(f"monster {monster_id!r} spawnable must be boolean")

    spells = _coerce_string_list(payload.get("spells"))
    starter_armour = _coerce_string_list(payload.get("starter_armour"))
    starter_items = _coerce_string_list(payload.get("starter_items"))

    normalized = {
        "monster_id": monster_id,
        "name": str(payload.get("name") or ""),
        "level": _coerce_int(payload.get("level")),
        "hp_max": _coerce_int(payload.get("hp_max")),
        "armour_class": _coerce_int(payload.get("armour_class")),
        "spawn_years": json.dumps(spawn_years, separators=(",", ":")),
        "spawnable": spawnable_flag,
        "taunt": str(payload.get("taunt") or ""),
        "stats_json": json.dumps(dict(stats), separators=(",", ":"), sort_keys=True),
        "innate_attack_json": json.dumps(
            _normalize_innate_attack(innate, monster_id=monster_id),
            separators=(",", ":"),
            sort_keys=True,
        ),
        "exp_bonus": _coerce_optional_int(payload.get("exp_bonus")),
        "ions_min": _coerce_optional_int(payload.get("ions_min")),
        "ions_max": _coerce_optional_int(payload.get("ions_max")),
        "riblets_min": _coerce_optional_int(payload.get("riblets_min")),
        "riblets_max": _coerce_optional_int(payload.get("riblets_max")),
        "spells_json": json.dumps(
            spells,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "starter_armour_json": json.dumps(
            starter_armour,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "starter_items_json": json.dumps(
            starter_items,
            separators=(",", ":"),
            sort_keys=True,
        ),
    }
    return normalized


def _decode_monster_row(row: sqlite3.Row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None

    def _json_or(default: Any, raw: Any) -> Any:
        if isinstance(raw, str) and raw.strip():
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                return default
            if isinstance(value, type(default)):
                return value
        return default

    spawn_years_raw = _json_or([], row.get("spawn_years"))
    spawn_years = []
    for value in spawn_years_raw:
        try:
            spawn_years.append(int(value))
        except (TypeError, ValueError):
            continue

    spells_raw = _json_or([], row.get("spells_json"))
    spells_list = [str(item) for item in spells_raw if item not in (None, "")]

    armour_raw = _json_or([], row.get("starter_armour_json"))
    armour_list = [str(item) for item in armour_raw if item not in (None, "")]

    items_raw = _json_or([], row.get("starter_items_json"))
    items_list = [str(item) for item in items_raw if item not in (None, "")]

    monster: Dict[str, Any] = {
        "monster_id": row.get("monster_id"),
        "name": row.get("name") or "",
        "level": _coerce_int(row.get("level"), default=0),
        "hp_max": _coerce_int(row.get("hp_max"), default=0),
        "armour_class": _coerce_int(row.get("armour_class"), default=0),
        "spawn_years": spawn_years,
        "spawnable": bool(_coerce_int(row.get("spawnable"), default=0)),
        "taunt": row.get("taunt") or "",
        "stats": _json_or({}, row.get("stats_json")),
        "innate_attack": _json_or({}, row.get("innate_attack_json")),
        "exp_bonus": _coerce_optional_int(row.get("exp_bonus")),
        "ions_min": _coerce_optional_int(row.get("ions_min")),
        "ions_max": _coerce_optional_int(row.get("ions_max")),
        "riblets_min": _coerce_optional_int(row.get("riblets_min")),
        "riblets_max": _coerce_optional_int(row.get("riblets_max")),
        "spells": spells_list,
        "starter_armour": armour_list,
        "starter_items": items_list,
    }

    innate = monster.get("innate_attack")
    if isinstance(innate, dict):
        line = innate.get("line")
        if not isinstance(line, str) or not line.strip():
            innate["line"] = DEFAULT_INNATE_ATTACK_LINE

    return monster

__all__ = [
    "SQLiteConnectionManager",
    "SQLiteItemsInstanceStore",
    "SQLiteMonstersInstanceStore",
    "SQLiteRuntimeKVStore",
    "get_stores",
]

if TYPE_CHECKING:
    from .storage import StateStores

def _resolve_db_path(db_path: Optional[os.PathLike[str] | str]) -> Path:
    if db_path is not None:
        return Path(db_path)
    return get_state_database_path()


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
            _begin_immediate(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    version INTEGER NOT NULL
                )
                """
            )
            row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_meta(version) VALUES (0)")
                version = 0
            else:
                version = _coerce_int(row[0], default=0)

            migrations: Sequence[tuple[int, Callable[[sqlite3.Connection], None]]] = (
                (1, self._migrate_to_v1),
                (2, self._migrate_to_v2),
                (3, self._migrate_to_v3),
                (4, self._migrate_to_v4),
                (5, self._migrate_to_v5),
                (6, self._migrate_to_v6),
            )

            for target_version, migration in migrations:
                if version < target_version:
                    migration(conn)
                    conn.execute(
                        "UPDATE schema_meta SET version = ?",
                        (target_version,),
                    )
                    version = target_version

    def upsert_item_catalog(self, item_id: str, data_json: str) -> None:
        conn = self.connect()
        with conn:
            _begin_immediate(conn)
            conn.execute(
                """
                INSERT INTO items_catalog (item_id, data_json)
                VALUES (?, ?)
                ON CONFLICT(item_id) DO UPDATE SET data_json = excluded.data_json
                """,
                (str(item_id), str(data_json)),
            )

    def get_item_catalog(self, item_id: str) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        cur = conn.execute(
            "SELECT data_json FROM items_catalog WHERE item_id = ?",
            (str(item_id),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        raw = row["data_json"]
        if not isinstance(raw, str):
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Invalid JSON for item %s in catalog", item_id)
            return None
        if isinstance(data, dict):
            data.setdefault("item_id", str(item_id))
            return data
        logger.error("Catalog row for item %s did not decode to an object", item_id)
        return None

    def list_spawnable_items(self) -> Iterable[Dict[str, Any]]:
        conn = self.connect()
        sql = (
            "SELECT item_id, data_json FROM items_catalog "
            "WHERE json_extract(data_json, '$.spawnable') = 1"
        )
        _debug_query_plan(conn, sql, tuple())
        cur = conn.execute(sql)
        results: list[Dict[str, Any]] = []
        for row in cur.fetchall():
            raw = row["data_json"]
            if not isinstance(raw, str):
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.error("Invalid JSON for item %s in spawnable list", row["item_id"])
                continue
            if isinstance(data, dict):
                data.setdefault("item_id", row["item_id"])
                results.append(data)
        return results

    def upsert_monster_catalog(self, monster_id: str, data_json: str) -> None:
        try:
            payload = json.loads(data_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON payload for monster {monster_id}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"monster catalog payload must be an object: {monster_id}")
        record = dict(payload)
        record.setdefault("monster_id", monster_id)
        normalized = _normalize_monster_catalog_entry(record)

        conn = self.connect()
        columns = (
            "monster_id, name, level, hp_max, armour_class, spawn_years, spawnable, "
            "taunt, stats_json, innate_attack_json, exp_bonus, ions_min, ions_max, "
            "riblets_min, riblets_max, spells_json, starter_armour_json, starter_items_json"
        )
        placeholders = (
            ":monster_id, :name, :level, :hp_max, :armour_class, :spawn_years, :spawnable, "
            ":taunt, :stats_json, :innate_attack_json, :exp_bonus, :ions_min, :ions_max, "
            ":riblets_min, :riblets_max, :spells_json, :starter_armour_json, :starter_items_json"
        )
        sql = (
            f"INSERT INTO monsters_catalog ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT(monster_id) DO UPDATE SET "
            "name=excluded.name, level=excluded.level, hp_max=excluded.hp_max, "
            "armour_class=excluded.armour_class, spawn_years=excluded.spawn_years, "
            "spawnable=excluded.spawnable, taunt=excluded.taunt, "
            "stats_json=excluded.stats_json, innate_attack_json=excluded.innate_attack_json, "
            "exp_bonus=excluded.exp_bonus, ions_min=excluded.ions_min, ions_max=excluded.ions_max, "
            "riblets_min=excluded.riblets_min, riblets_max=excluded.riblets_max, "
            "spells_json=excluded.spells_json, starter_armour_json=excluded.starter_armour_json, "
            "starter_items_json=excluded.starter_items_json, updated_at=CURRENT_TIMESTAMP"
        )

        with conn:
            _begin_immediate(conn)
            conn.execute(sql, normalized)

    def get_monster_catalog(self, monster_id: str) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        columns = ", ".join(_MONSTER_CATALOG_COLUMNS)
        cur = conn.execute(
            f"SELECT {columns} FROM monsters_catalog WHERE monster_id = ?",
            (str(monster_id),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        monster = _decode_monster_row(row)
        if monster is None:
            logger.error("Invalid monster catalog row for %s", monster_id)
            return None
        return monster

    def list_spawnable_monsters(self) -> Iterable[Dict[str, Any]]:
        conn = self.connect()
        columns = ", ".join(_MONSTER_CATALOG_COLUMNS)
        sql = f"SELECT {columns} FROM monsters_catalog WHERE spawnable = 1"
        _debug_query_plan(conn, sql, tuple())
        cur = conn.execute(sql)
        results: list[Dict[str, Any]] = []
        for row in cur.fetchall():
            monster = _decode_monster_row(row)
            if monster is None:
                continue
            results.append(monster)
        return results

    def _migrate_to_v1(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items_instances (
                iid TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                year INTEGER NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                owner TEXT,
                enchant INT,
                condition INT,
                charges INTEGER DEFAULT 0,
                origin TEXT,
                drop_source TEXT,
                created_at INTEGER NOT NULL CHECK(created_at >= 0)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS items_at_idx
            ON items_instances(year, x, y, created_at, iid)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS items_owner_idx
            ON items_instances(owner, created_at, iid)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS items_origin_idx
            ON items_instances(origin)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monsters_instances (
                instance_id TEXT PRIMARY KEY,
                monster_id TEXT NOT NULL,
                year INTEGER NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                hp_cur INT,
                hp_max INT,
                stats_json TEXT,
                created_at INTEGER NOT NULL CHECK(created_at >= 0)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS monsters_at_idx
            ON monsters_instances(year, x, y, created_at, instance_id)
            """
        )

    def _migrate_to_v2(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items_catalog (
                item_id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monsters_catalog (
                monster_id TEXT PRIMARY KEY,
                name TEXT,
                level INT,
                hp_max INT,
                armour_class INT,
                spawn_years TEXT,
                spawnable INT,
                taunt TEXT,
                stats_json TEXT,
                innate_attack_json TEXT,
                exp_bonus INT,
                ions_min INT,
                ions_max INT,
                riblets_min INT,
                riblets_max INT,
                spells_json TEXT,
                starter_armour_json TEXT,
                starter_items_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

    def _migrate_to_v3(self, conn: sqlite3.Connection) -> None:
        conn.execute("DROP INDEX IF EXISTS items_at_idx")
        conn.execute("DROP INDEX IF EXISTS items_owner_idx")
        conn.execute("DROP INDEX IF EXISTS monsters_at_idx")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS items_at_idx
            ON items_instances(year, x, y, created_at, iid)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS items_owner_idx
            ON items_instances(owner, created_at, iid)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS items_origin_idx
            ON items_instances(origin)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS monsters_at_idx
            ON monsters_instances(year, x, y, created_at, instance_id)
            """
        )

    def _migrate_to_v4(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("PRAGMA table_info(items_instances)")
        existing = {row[1] for row in cur.fetchall() if len(row) > 1}
        if "charges" in existing:
            return
        conn.execute(
            "ALTER TABLE items_instances ADD COLUMN charges INTEGER DEFAULT 0"
        )

    def _migrate_to_v5(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("PRAGMA table_info(monsters_catalog)")
        existing = {row[1] for row in cur.fetchall() if len(row) > 1}
        required = {
            "monster_id",
            "name",
            "level",
            "hp_max",
            "armour_class",
            "spawn_years",
            "spawnable",
            "taunt",
            "stats_json",
            "innate_attack_json",
            "exp_bonus",
            "ions_min",
            "ions_max",
            "riblets_min",
            "riblets_max",
            "spells_json",
            "starter_armour_json",
            "starter_items_json",
            "created_at",
            "updated_at",
        }

        needs_rebuild = False
        if not existing:
            needs_rebuild = True
        elif "data_json" in existing:
            needs_rebuild = True
        elif not required.issubset(existing):
            needs_rebuild = True

        if not needs_rebuild:
            return

        conn.execute("ALTER TABLE IF EXISTS monsters_catalog RENAME TO monsters_catalog_legacy")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monsters_catalog (
                monster_id TEXT PRIMARY KEY,
                name TEXT,
                level INT,
                hp_max INT,
                armour_class INT,
                spawn_years TEXT,
                spawnable INT,
                taunt TEXT,
                stats_json TEXT,
                innate_attack_json TEXT,
                exp_bonus INT,
                ions_min INT,
                ions_max INT,
                riblets_min INT,
                riblets_max INT,
                spells_json TEXT,
                starter_armour_json TEXT,
                starter_items_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        legacy_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='monsters_catalog_legacy'"
        ).fetchone()
        if legacy_exists is None:
            return

        rows = conn.execute(
            "SELECT monster_id, data_json FROM monsters_catalog_legacy"
        ).fetchall()
        insert_sql = (
            "INSERT INTO monsters_catalog (monster_id, name, level, hp_max, armour_class, "
            "spawn_years, spawnable, taunt, stats_json, innate_attack_json, exp_bonus, "
            "ions_min, ions_max, riblets_min, riblets_max, spells_json, starter_armour_json, "
            "starter_items_json, created_at, updated_at) "
            "VALUES (:monster_id, :name, :level, :hp_max, :armour_class, :spawn_years, :spawnable, "
            ":taunt, :stats_json, :innate_attack_json, :exp_bonus, :ions_min, :ions_max, :riblets_min, "
            ":riblets_max, :spells_json, :starter_armour_json, :starter_items_json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )

        for row in rows:
            raw = row["data_json"]
            if not isinstance(raw, str):
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, Mapping):
                continue
            payload = dict(payload)
            payload.setdefault("monster_id", row["monster_id"])
            try:
                normalized = _normalize_monster_catalog_entry(payload)
            except ValueError:
                continue
            conn.execute(insert_sql, normalized)

        conn.execute("DROP TABLE IF EXISTS monsters_catalog_legacy")

    def _migrate_to_v6(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("PRAGMA table_info(monsters_instances)")
        existing = {row[1] for row in cur.fetchall() if len(row) > 1}

        columns: Sequence[tuple[str, str]] = (
            ("target_player_id", "TEXT"),
            ("ai_state_json", "TEXT"),
            ("bag_json", "TEXT"),
            ("timers_json", "TEXT"),
        )

        for column, ddl in columns:
            if column not in existing:
                conn.execute(f"ALTER TABLE monsters_instances ADD COLUMN {column} {ddl}")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS monsters_target_idx
            ON monsters_instances(target_player_id)
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
        "charges",
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

    def snapshot(self) -> Iterable[Dict[str, Any]]:
        conn = self._connection()
        cur = conn.execute(
            "SELECT iid, item_id, year, x, y, owner, enchant, condition, charges, origin, drop_source, created_at "
            "FROM items_instances ORDER BY created_at ASC, iid ASC"
        )
        return [self._row_to_dict(row) for row in cur.fetchall()]

    def replace_all(self, records: Iterable[Dict[str, Any]]) -> None:
        if not os.getenv("MUTANTS_ALLOW_REPLACE_ALL"):
            raise RuntimeError(
                "sqlite_store.replace_all is disabled; use targeted ops or bulk_insert_*"
            )
        payloads: list[Dict[str, Any]] = []
        base_created = _epoch_ms()
        order = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            normalized = self._normalize_record(record, base_created + order)
            if normalized is None:
                continue
            payloads.append(normalized)
            order += 1

        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            conn.execute("DELETE FROM items_instances")
            if payloads:
                columns = ", ".join(self._COLUMNS)
                placeholders = ", ".join("?" for _ in self._COLUMNS)
                values = [tuple(payload[col] for col in self._COLUMNS) for payload in payloads]
                conn.executemany(
                    f"INSERT INTO items_instances ({columns}) VALUES ({placeholders})",
                    values,
                )

    def bulk_insert(self, records: Iterable[Dict[str, Any]]) -> None:
        payloads: list[Dict[str, Any]] = []
        base_created = _epoch_ms()
        order = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            normalized = self._normalize_record(record, base_created + order)
            if normalized is None:
                continue
            payloads.append(normalized)
            if isinstance(record, dict):
                record.setdefault("created_at", normalized["created_at"])
            order += 1

        if not payloads:
            return

        columns = ", ".join(self._COLUMNS)
        placeholders = ", ".join("?" for _ in self._COLUMNS)
        values = [tuple(payload[col] for col in self._COLUMNS) for payload in payloads]

        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            conn.executemany(
                f"INSERT INTO items_instances ({columns}) VALUES ({placeholders})",
                values,
            )

    def bulk_insert_items(self, records: Iterable[Dict[str, Any]]) -> None:
        self.bulk_insert(records)

    def _normalize_record(
        self, record: Dict[str, Any], default_created: int
    ) -> Optional[Dict[str, Any]]:
        iid = record.get("iid") or record.get("instance_id")
        item_id = record.get("item_id") or record.get("catalog_id")
        if iid is None or item_id is None:
            return None

        payload: Dict[str, Any] = {key: None for key in self._COLUMNS}
        payload["iid"] = str(iid)
        payload["item_id"] = str(item_id)
        payload["year"] = _coerce_int(record.get("year"))
        payload["x"] = _coerce_int(record.get("x"))
        payload["y"] = _coerce_int(record.get("y"))
        owner = record.get("owner")
        payload["owner"] = str(owner) if owner is not None else None
        payload["enchant"] = _coerce_int(record.get("enchant"))
        payload["condition"] = _coerce_int(record.get("condition"), default=100)
        payload["charges"] = _coerce_int(record.get("charges"))
        origin = record.get("origin")
        payload["origin"] = str(origin) if origin is not None else None
        drop_source = record.get("drop_source")
        payload["drop_source"] = str(drop_source) if drop_source is not None else None
        payload["created_at"] = _normalize_created_at(
            record.get("created_at"), default=default_created
        )
        return payload

    def get_by_iid(self, iid: str) -> Optional[Dict[str, Any]]:
        conn = self._connection()
        cur = conn.execute(
            "SELECT iid, item_id, year, x, y, owner, enchant, condition, charges, origin, drop_source, created_at "
            "FROM items_instances WHERE iid = ?",
            (str(iid),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        conn = self._connection()
        sql = (
            "SELECT iid, item_id, year, x, y, owner, enchant, condition, charges, origin, drop_source, created_at "
            "FROM items_instances WHERE year = ? AND x = ? AND y = ? "
            "ORDER BY created_at ASC, iid ASC"
        )
        params: Tuple[int, int, int] = (year, x, y)
        _debug_query_plan(conn, sql, params)
        cur = conn.execute(sql, params)
        return [self._row_to_dict(row) for row in cur.fetchall()]

    def list_by_owner(self, owner: str) -> Iterable[Dict[str, Any]]:
        conn = self._connection()
        sql = (
            "SELECT iid, item_id, year, x, y, owner, enchant, condition, charges, origin, drop_source, created_at "
            "FROM items_instances WHERE owner = ? ORDER BY created_at ASC, iid ASC"
        )
        params = (str(owner),)
        _debug_query_plan(conn, sql, params)
        cur = conn.execute(sql, params)
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

        created = _normalize_created_at(payload.get("created_at"))
        payload["created_at"] = created
        if isinstance(rec, dict):
            rec.setdefault("created_at", created)

        payload["year"] = _coerce_int(payload.get("year"))
        payload["x"] = _coerce_int(payload.get("x"))
        payload["y"] = _coerce_int(payload.get("y"))
        if payload.get("owner") is not None:
            payload["owner"] = str(payload["owner"])
        payload["charges"] = _coerce_int(payload.get("charges"))

        columns = ", ".join(self._COLUMNS)
        placeholders = ", ".join("?" for _ in self._COLUMNS)
        values = tuple(payload[key] for key in self._COLUMNS)

        conn = self._connection()
        try:
            with conn:
                _begin_immediate(conn)
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
            if key == "created_at":
                value = _normalize_created_at(value)
            elif key in {"year", "x", "y", "enchant", "condition", "charges"}:
                value = _coerce_int(value)
            if key == "owner" and value is not None:
                value = str(value)
            updates.append(f"{key} = ?")
            values.append(value)
        values.append(str(iid))

        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            cur = conn.execute(
                f"UPDATE items_instances SET {', '.join(updates)} WHERE iid = ?",
                values,
            )
            if cur.rowcount == 0:
                raise KeyError(str(iid))

    def delete(self, iid: str) -> None:
        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            cur = conn.execute(
                "DELETE FROM items_instances WHERE iid = ?",
                (str(iid),),
            )
            if cur.rowcount == 0:
                raise KeyError(str(iid))

    def delete_by_origin(self, origin: str) -> None:
        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            conn.execute(
                "DELETE FROM items_instances WHERE origin = ?",
                (str(origin),),
            )

    def delete_items_by_origin(self, origin: str) -> None:
        self.delete_by_origin(origin)


class SQLiteRuntimeKVStore:
    __slots__ = ("_manager",)

    def __init__(self, manager: SQLiteConnectionManager) -> None:
        self._manager = manager

    def _connection(self) -> sqlite3.Connection:
        return self._manager.connect()

    def get(self, key: str) -> Optional[str]:
        conn = self._connection()
        cur = conn.execute(
            "SELECT value FROM runtime_kv WHERE key = ?",
            (str(key),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        value = row["value"]
        return str(value) if value is not None else None

    def set(self, key: str, value: str) -> None:
        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            conn.execute(
                """
                INSERT INTO runtime_kv(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(key), str(value)),
            )

    def delete(self, key: str) -> None:
        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            conn.execute(
                "DELETE FROM runtime_kv WHERE key = ?",
                (str(key),),
            )


class SQLiteMonstersInstanceStore:
    """SQLite-backed implementation of :class:`MonstersInstanceStore`."""

    __slots__ = ("_manager",)

    _COLUMNS: Sequence[str] = (
        "instance_id",
        "monster_id",
        "year",
        "x",
        "y",
        "hp_cur",
        "hp_max",
        "stats_json",
        "created_at",
        "target_player_id",
        "ai_state_json",
        "bag_json",
        "timers_json",
    )

    def __init__(self, manager: SQLiteConnectionManager) -> None:
        self._manager = manager

    def _connection(self) -> sqlite3.Connection:
        return self._manager.connect()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {key: row[key] for key in self._COLUMNS}

    def _row_to_payload(self, row: sqlite3.Row) -> Dict[str, Any]:
        record = self._row_to_dict(row)
        stats_raw = record.get("stats_json")
        payload: Dict[str, Any]
        if isinstance(stats_raw, str) and stats_raw.strip():
            try:
                decoded = json.loads(stats_raw)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, dict):
                payload = dict(decoded)
            else:
                payload = {}
        else:
            payload = {}

        payload.setdefault("instance_id", record.get("instance_id"))
        payload.setdefault("monster_id", record.get("monster_id"))

        pos = payload.get("pos")
        year = record.get("year")
        x = record.get("x")
        y = record.get("y")
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            coords = []
            for idx, value in enumerate(pos):
                try:
                    coords.append(int(value))
                except (TypeError, ValueError):
                    coords.append(int([year, x, y][idx] or 0))
            payload["pos"] = coords
        else:
            coords = [year, x, y]
            payload["pos"] = [int(v) if v is not None else 0 for v in coords]

        hp = payload.get("hp")
        hp_cur = int(record.get("hp_cur") or 0)
        hp_max = int(record.get("hp_max") or 0)
        if isinstance(hp, dict):
            try:
                hp_cur = int(hp.get("current", hp_cur))
            except (TypeError, ValueError):
                hp_cur = int(record.get("hp_cur") or 0)
            try:
                hp_max = int(hp.get("max", hp_max))
            except (TypeError, ValueError):
                hp_max = int(record.get("hp_max") or 0)
        payload["hp"] = {"current": hp_cur, "max": hp_max}

        for field in ("target_player_id", "ai_state_json", "bag_json"):
            value = record.get(field)
            if value is not None and field not in payload:
                payload[field] = value

        timers_raw = record.get("timers_json")
        if isinstance(timers_raw, str) and timers_raw.strip():
            try:
                decoded = json.loads(timers_raw)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, Mapping):
                timers_payload = decoded.get("status_effects") or decoded.get("statuses")
            elif isinstance(decoded, list):
                timers_payload = decoded
            else:
                timers_payload = None
            if timers_payload is not None and "status_effects" not in payload:
                payload["status_effects"] = timers_payload

        return payload

    def _normalize_payload(self, record: Dict[str, Any], order: int) -> Dict[str, Any]:
        payload = {key: None for key in self._COLUMNS}

        instance_id = record.get("instance_id")
        monster_id = record.get("monster_id")
        if instance_id is None:
            raise KeyError("instance_id")
        if monster_id is None:
            raise KeyError("monster_id")

        payload["instance_id"] = str(instance_id)
        payload["monster_id"] = str(monster_id)

        pos = record.get("pos")
        year = x = y = None
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            try:
                year = int(pos[0])
            except (TypeError, ValueError):
                year = None
            try:
                x = int(pos[1])
            except (TypeError, ValueError):
                x = None
            try:
                y = int(pos[2])
            except (TypeError, ValueError):
                y = None
        else:
            try:
                year = int(record.get("year"))
            except (TypeError, ValueError):
                year = None
            try:
                x = int(record.get("x"))
            except (TypeError, ValueError):
                x = None
            try:
                y = int(record.get("y"))
            except (TypeError, ValueError):
                y = None
        payload["year"] = _coerce_int(year)
        payload["x"] = _coerce_int(x)
        payload["y"] = _coerce_int(y)

        hp_cur = hp_max = 0
        hp = record.get("hp")
        if isinstance(hp, dict):
            try:
                hp_cur = int(hp.get("current", 0))
            except (TypeError, ValueError):
                hp_cur = 0
            try:
                hp_max = int(hp.get("max", hp_cur))
            except (TypeError, ValueError):
                hp_max = hp_cur
        else:
            try:
                hp_cur = int(record.get("hp_cur", 0))
            except (TypeError, ValueError):
                hp_cur = 0
            try:
                hp_max = int(record.get("hp_max", hp_cur))
            except (TypeError, ValueError):
                hp_max = hp_cur
        payload["hp_cur"] = _coerce_int(hp_cur)
        payload["hp_max"] = _coerce_int(hp_max)

        payload["stats_json"] = json.dumps(record, sort_keys=True, separators=(",", ":"))

        payload["target_player_id"] = record.get("target_player_id")
        payload["ai_state_json"] = record.get("ai_state_json")
        payload["bag_json"] = record.get("bag_json")
        timers_field = record.get("timers_json")
        if timers_field is None:
            timers_payload = record.get("status_effects") or record.get("timers")
            if isinstance(timers_payload, (list, tuple)):
                try:
                    timers_field = json.dumps(
                        {"status_effects": list(timers_payload)},
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                except TypeError:
                    timers_field = None
        payload["timers_json"] = timers_field

        created_at = record.get("created_at")
        default_created = order if order is not None else _epoch_ms()
        payload["created_at"] = _normalize_created_at(
            created_at, default=default_created
        )

        return payload

    def get(self, mid: str) -> Optional[Dict[str, Any]]:
        conn = self._connection()
        cur = conn.execute(
            "SELECT instance_id, monster_id, year, x, y, hp_cur, hp_max, stats_json, created_at, "
            "target_player_id, ai_state_json, bag_json, timers_json "
            "FROM monsters_instances WHERE instance_id = ?",
            (str(mid),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_payload(row)

    def snapshot(self) -> Iterable[Dict[str, Any]]:
        conn = self._connection()
        cur = conn.execute(
            "SELECT instance_id, monster_id, year, x, y, hp_cur, hp_max, stats_json, created_at, "
            "target_player_id, ai_state_json, bag_json, timers_json "
            "FROM monsters_instances ORDER BY created_at ASC, instance_id ASC"
        )
        return [self._row_to_payload(row) for row in cur.fetchall()]

    def replace_all(self, records: Iterable[Dict[str, Any]]) -> None:
        if not os.getenv("MUTANTS_ALLOW_REPLACE_ALL"):
            raise RuntimeError(
                "sqlite_store.replace_all is disabled; use targeted ops or bulk_insert_*"
            )
        payloads = []
        base_created = _epoch_ms()
        order = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            payloads.append(self._normalize_payload(record, base_created + order))
            order += 1

        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            conn.execute("DELETE FROM monsters_instances")
            if payloads:
                columns = ", ".join(self._COLUMNS)
                placeholders = ", ".join("?" for _ in self._COLUMNS)
                values = [tuple(payload[col] for col in self._COLUMNS) for payload in payloads]
                conn.executemany(
                    f"INSERT INTO monsters_instances ({columns}) VALUES ({placeholders})",
                    values,
                )

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        import logging

        LOG = logging.getLogger(__name__)
        cache_attr = getattr(self, "_cache", None)
        try:
            cache_size = len(cache_attr) if cache_attr is not None else 0
        except TypeError:
            cache_size = 0
        LOG.warning(
            ">>> _list_at called for %s,%s,%s. Cache size: %s",
            year,
            x,
            y,
            cache_size,
        )

        conn = self._connection()
        sql = (
            "SELECT instance_id, monster_id, year, x, y, hp_cur, hp_max, stats_json, created_at, "
            "target_player_id, ai_state_json, bag_json, timers_json "
            "FROM monsters_instances WHERE year = ? AND x = ? AND y = ? "
            "ORDER BY created_at ASC, instance_id ASC"
        )
        params: Tuple[int, int, int] = (year, x, y)
        _debug_query_plan(conn, sql, params)
        cur = conn.execute(sql, params)
        results = [self._row_to_dict(row) for row in cur.fetchall()]
        LOG.warning("<<< _list_at returning %s results.", len(results))
        return results

    def count_alive(self, year: int) -> int:
        conn = self._connection()
        sql = (
            "SELECT COUNT(1) AS total FROM monsters_instances "
            "WHERE year = ? AND hp_cur > 0"
        )
        params = (_coerce_int(year),)
        _debug_query_plan(conn, sql, params)
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return 0
        try:
            return int(row["total"])
        except (KeyError, TypeError, ValueError):
            return 0

    def spawn(self, rec: Dict[str, Any]) -> None:
        normalized = self._normalize_payload(dict(rec), _epoch_ms())
        instance_id = normalized["instance_id"]
        monster_id = normalized["monster_id"]

        if isinstance(rec, dict):
            rec.setdefault("created_at", normalized.get("created_at"))

        columns = ", ".join(self._COLUMNS)
        placeholders = ", ".join("?" for _ in self._COLUMNS)
        values = tuple(normalized[key] for key in self._COLUMNS)

        conn = self._connection()
        try:
            with conn:
                _begin_immediate(conn)
                conn.execute(
                    f"INSERT INTO monsters_instances ({columns}) VALUES ({placeholders})",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise KeyError(str(instance_id)) from exc

    def update_fields(self, mid: str, **fields: Any) -> None:
        if not fields:
            return
        updates = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in self._COLUMNS or key == "instance_id":
                raise KeyError(key)
            if key == "created_at":
                value = _normalize_created_at(value)
            elif key in {"year", "x", "y", "hp_cur", "hp_max"}:
                value = _coerce_int(value)
            updates.append(f"{key} = ?")
            values.append(value)
        values.append(str(mid))

        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            cur = conn.execute(
                f"UPDATE monsters_instances SET {', '.join(updates)} WHERE instance_id = ?",
                values,
            )
            if cur.rowcount == 0:
                raise KeyError(str(mid))

    def delete(self, mid: str) -> None:
        conn = self._connection()
        with conn:
            _begin_immediate(conn)
            cur = conn.execute(
                "DELETE FROM monsters_instances WHERE instance_id = ?",
                (str(mid),),
            )
            if cur.rowcount == 0:
                raise KeyError(str(mid))


def get_stores(db_path: Optional[os.PathLike[str] | str] = None) -> "StateStores":
    manager = SQLiteConnectionManager(db_path)
    return _build_state_stores(manager)


def _build_state_stores(manager: SQLiteConnectionManager) -> "StateStores":
    from .storage import StateStores

    return StateStores(
        items=SQLiteItemsInstanceStore(manager),
        monsters=SQLiteMonstersInstanceStore(manager),
        runtime_kv=SQLiteRuntimeKVStore(manager),
    )
