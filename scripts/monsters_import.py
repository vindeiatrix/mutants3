#!/usr/bin/env python3
"""Import monsters catalog data into the SQLite state database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable


CATALOG_REQUIRED_FIELDS = {
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

STAT_FIELDS = {"str", "int", "wis", "dex", "con", "cha"}
INNATE_ATTACK_FIELDS = {"name", "power_base", "power_per_level"}


def _ensure_database(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
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
        CREATE TABLE IF NOT EXISTS monsters_instances (
            instance_id TEXT PRIMARY KEY,
            monster_id TEXT,
            year INT,
            x INT,
            y INT,
            hp_cur INT,
            hp_max INT,
            stats_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _load_catalog(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"catalog JSON not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("catalog JSON must be a list of objects")
    return data


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"expected integer, got {value!r}") from exc


def _normalize_spawn_years(raw: Any, *, monster_id: str) -> list[int]:
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError(f"monster {monster_id!r} spawn_years must be a non-empty list")
    years: list[int] = []
    for item in raw:
        try:
            years.append(int(item))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"monster {monster_id!r} spawn_years entries must be integers"
            ) from exc
    if len(years) == 2 and years[0] <= years[1]:
        expanded = list(range(years[0], years[1] + 1))
        return expanded
    return sorted(dict.fromkeys(years))


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, "", []):
        return []
    return [str(value)]


def _validate_monster(entry: dict[str, Any]) -> None:
    present = set(entry)
    missing = sorted(CATALOG_REQUIRED_FIELDS - present)
    if missing:
        monster_ref = entry.get("monster_id") or entry.get("id") or "<unknown>"
        raise ValueError(f"monster {monster_ref!r} missing fields: {', '.join(missing)}")

    stats = entry.get("stats")
    if not isinstance(stats, dict):
        raise ValueError(f"monster {entry.get('monster_id')} stats must be an object")
    missing_stats = sorted(STAT_FIELDS - set(stats))
    if missing_stats:
        raise ValueError(
            f"monster {entry.get('monster_id')} stats missing: {', '.join(missing_stats)}"
        )

    innate = entry.get("innate_attack")
    if not isinstance(innate, dict):
        raise ValueError(
            f"monster {entry.get('monster_id')} innate_attack must be an object"
        )
    missing_innate = sorted(INNATE_ATTACK_FIELDS - set(innate))
    if missing_innate:
        raise ValueError(
            f"monster {entry.get('monster_id')} innate_attack missing: {', '.join(missing_innate)}"
        )


def _normalize_monster(entry: dict[str, Any]) -> dict[str, Any]:
    _validate_monster(entry)

    monster_id = str(entry.get("monster_id") or entry.get("id"))
    if not monster_id:
        raise ValueError("monster missing monster_id")

    spawn_years = _normalize_spawn_years(entry.get("spawn_years"), monster_id=monster_id)

    spawnable = entry.get("spawnable")
    if isinstance(spawnable, bool):
        spawnable_flag = 1 if spawnable else 0
    elif isinstance(spawnable, (int, float)):
        spawnable_flag = 1 if int(spawnable) else 0
    else:
        raise ValueError(f"monster {monster_id!r} spawnable must be boolean")

    stats = entry.get("stats") or {}
    innate = entry.get("innate_attack") or {}

    exp_bonus = entry.get("exp_bonus")
    ions_min = entry.get("ions_min")
    ions_max = entry.get("ions_max")
    riblets_min = entry.get("riblets_min")
    riblets_max = entry.get("riblets_max")

    spells = _coerce_string_list(entry.get("spells"))
    starter_armour = _coerce_string_list(entry.get("starter_armour"))
    starter_items = _coerce_string_list(entry.get("starter_items"))

    record = {
        "monster_id": monster_id,
        "name": str(entry.get("name")),
        "level": _coerce_int(entry.get("level")) or 0,
        "hp_max": _coerce_int(entry.get("hp_max")) or 0,
        "armour_class": _coerce_int(entry.get("armour_class")) or 0,
        "spawn_years": json.dumps(spawn_years, separators=(",", ":")),
        "spawnable": spawnable_flag,
        "taunt": str(entry.get("taunt") or ""),
        "stats_json": json.dumps(stats, separators=(",", ":"), sort_keys=True),
        "innate_attack_json": json.dumps(innate, separators=(",", ":"), sort_keys=True),
        "exp_bonus": _coerce_int(exp_bonus),
        "ions_min": _coerce_int(ions_min),
        "ions_max": _coerce_int(ions_max),
        "riblets_min": _coerce_int(riblets_min),
        "riblets_max": _coerce_int(riblets_max),
        "spells_json": json.dumps(spells, separators=(",", ":"), sort_keys=True),
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
    return record


def _upsert_catalog(conn: sqlite3.Connection, records: Iterable[dict[str, Any]]) -> int:
    sql = (
        "INSERT INTO monsters_catalog (monster_id, name, level, hp_max, armour_class, "
        "spawn_years, spawnable, taunt, stats_json, innate_attack_json, exp_bonus, "
        "ions_min, ions_max, riblets_min, riblets_max, spells_json, starter_armour_json, "
        "starter_items_json) "
        "VALUES (:monster_id, :name, :level, :hp_max, :armour_class, :spawn_years, :spawnable, "
        ":taunt, :stats_json, :innate_attack_json, :exp_bonus, :ions_min, :ions_max, "
        ":riblets_min, :riblets_max, :spells_json, :starter_armour_json, :starter_items_json) "
        "ON CONFLICT(monster_id) DO UPDATE SET "
        "name=excluded.name, level=excluded.level, hp_max=excluded.hp_max, "
        "armour_class=excluded.armour_class, spawn_years=excluded.spawn_years, "
        "spawnable=excluded.spawnable, taunt=excluded.taunt, "
        "stats_json=excluded.stats_json, innate_attack_json=excluded.innate_attack_json, "
        "exp_bonus=excluded.exp_bonus, ions_min=excluded.ions_min, ions_max=excluded.ions_max, "
        "riblets_min=excluded.riblets_min, riblets_max=excluded.riblets_max, "
        "spells_json=excluded.spells_json, starter_armour_json=excluded.starter_armour_json, "
        "starter_items_json=excluded.starter_items_json, "
        "updated_at=CURRENT_TIMESTAMP"
    )

    normalized = [record for record in records]
    if not normalized:
        return 0

    with conn:
        conn.executemany(sql, normalized)
    return len(normalized)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load monsters catalog data into the SQLite state database"
    )
    parser.add_argument(
        "--catalog",
        required=True,
        help="Path to the monsters catalog JSON file",
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to the SQLite state database",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    catalog_path = Path(args.catalog)
    db_path = Path(args.db)

    try:
        entries = list(_load_catalog(catalog_path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: failed to read catalog: {exc}", file=sys.stderr)
        return 1

    try:
        normalized = [_normalize_monster(entry) for entry in entries]
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    conn = _ensure_database(db_path)
    try:
        inserted = _upsert_catalog(conn, normalized)
    except sqlite3.Error as exc:
        print(f"error: database failure: {exc}", file=sys.stderr)
        return 1

    print(f"Imported {inserted} monster(s) into catalog at {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
