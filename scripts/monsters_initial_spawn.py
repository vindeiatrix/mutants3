#!/usr/bin/env python3
"""Seed passive monster instances for a new world year."""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict, Iterable as TypingIterable, List, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mutants.registries.items_instances import mint_iid
from mutants.services.monster_entities import DEFAULT_INNATE_ATTACK_LINE, MonsterTemplate
from mutants.world import get_world_years, set_cli_years_override


def _ensure_tables(conn: sqlite3.Connection) -> None:
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


def _fetch_templates(conn: sqlite3.Connection) -> list[MonsterTemplate]:
    cursor = conn.execute(
        """
        SELECT monster_id, name, level, hp_max, armour_class, spawn_years, spawnable,
               taunt, stats_json, innate_attack_json, exp_bonus, ions_min, ions_max,
               riblets_min, riblets_max, spells_json, starter_armour_json, starter_items_json
        FROM monsters_catalog
        ORDER BY monster_id ASC
        """
    )
    templates: list[MonsterTemplate] = []
    for row in cursor.fetchall():
        try:
            spawn_years = json.loads(row["spawn_years"] or "[]")
        except json.JSONDecodeError:
            spawn_years = []
        try:
            stats = json.loads(row["stats_json"] or "{}")
        except json.JSONDecodeError:
            stats = {}
        try:
            innate_attack = json.loads(row["innate_attack_json"] or "{}")
        except json.JSONDecodeError:
            innate_attack = {}
        try:
            spells = json.loads(row["spells_json"] or "[]")
        except json.JSONDecodeError:
            spells = []
        try:
            starter_armour = json.loads(row["starter_armour_json"] or "[]")
        except json.JSONDecodeError:
            starter_armour = []
        try:
            starter_items = json.loads(row["starter_items_json"] or "[]")
        except json.JSONDecodeError:
            starter_items = []
        template = MonsterTemplate(
            monster_id=row["monster_id"],
            name=row["name"],
            level=int(row["level"] or 0),
            hp_max=int(row["hp_max"] or 0),
            armour_class=int(row["armour_class"] or 0),
            spawn_years=[int(y) for y in spawn_years if isinstance(y, int)] or [],
            spawnable=bool(int(row["spawnable"] or 0)),
            taunt=row["taunt"] or "",
            stats=stats if isinstance(stats, dict) else {},
            innate_attack=innate_attack if isinstance(innate_attack, dict) else {},
            exp_bonus=row["exp_bonus"],
            ions_min=row["ions_min"],
            ions_max=row["ions_max"],
            riblets_min=row["riblets_min"],
            riblets_max=row["riblets_max"],
            spells=[str(s) for s in spells if s is not None],
            starter_armour=[str(s) for s in starter_armour if s is not None],
            starter_items=[str(s) for s in starter_items if s is not None],
        )
        templates.append(template)
    return templates


def _item_exists(conn: sqlite3.Connection, item_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM items_catalog WHERE item_id = ? LIMIT 1",
        (item_id,),
    )
    return cur.fetchone() is not None


def _generate_positions(center_x: int, center_y: int, radius: int) -> Iterable[Tuple[int, int]]:
    candidates: list[Tuple[int, int, int]] = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            distance = abs(dx) + abs(dy)
            if distance > radius:
                continue
            candidates.append((distance, center_x + dx, center_y + dy))
    candidates.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    for _, x, y in candidates:
        yield x, y


def _plan_positions(
    count: int,
    center_x: int,
    center_y: int,
    radius: int,
    *,
    blocked: TypingIterable[Tuple[int, int]] | None = None,
) -> list[Tuple[int, int]]:
    coords: list[Tuple[int, int]] = []
    seen: set[Tuple[int, int]] = set(blocked or [])
    for x, y in _generate_positions(center_x, center_y, radius):
        if (x, y) in seen:
            continue
        coords.append((x, y))
        seen.add((x, y))
        if len(coords) >= count:
            break
    if len(coords) < count:
        raise RuntimeError(
            "not enough passable tiles generated for requested monster spawns"
        )
    return coords


def _mint_items(
    conn: sqlite3.Connection,
    item_ids: Sequence[str],
    *,
    owner: str,
    year: int,
    x: int,
    y: int,
    created_at: int,
    dry_run: bool,
) -> list[Tuple[str, str]]:
    minted: list[Tuple[str, str]] = []
    rows: list[tuple[Any, ...]] = []
    for item_id in item_ids:
        if not item_id:
            continue
        if not _item_exists(conn, item_id):
            continue
        iid = mint_iid()
        minted.append((item_id, iid))
        rows.append(
            (
                iid,
                item_id,
                year,
                x,
                y,
                owner,
                0,
                100,
                0,
                "monster_spawn",
                None,
                created_at,
            )
        )
    if rows and not dry_run:
        conn.executemany(
            """
            INSERT INTO items_instances (
                iid, item_id, year, x, y, owner, enchant, condition, charges,
                origin, drop_source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return minted


def _build_monster_payload(
    template: MonsterTemplate,
    instance_id: str,
    *,
    year: int,
    x: int,
    y: int,
    ions: int,
    riblets: int,
    inventory: Sequence[Tuple[str, str]],
    armour_iid: str | None,
) -> dict[str, Any]:
    spells = list(template.spells)
    innate = dict(template.innate_attack)
    innate.setdefault("line", DEFAULT_INNATE_ATTACK_LINE)

    items_payload = [
        {"item_id": item_id, "iid": iid, "origin": "monster_spawn"}
        for item_id, iid in inventory
    ]

    payload = {
        "instance_id": instance_id,
        "monster_id": template.monster_id,
        "name": template.name,
        "pos": [year, x, y],
        "hp": {"current": template.hp_max, "max": template.hp_max},
        "armour_class": template.armour_class,
        "level": template.level,
        "ions": ions,
        "riblets": riblets,
        "inventory": items_payload,
        "armour_wearing": armour_iid,
        "readied_spell": None,
        "target_player_id": None,
        "target_monster_id": None,
        "ready_target": None,
        "taunt": template.taunt,
        "innate_attack": innate,
        "spells": spells,
        "stats": dict(template.stats),
    }
    return payload


def _spawn_monsters(
    conn: sqlite3.Connection,
    templates: Iterable[MonsterTemplate],
    *,
    year: int,
    per_monster: int,
    center_x: int,
    center_y: int,
    radius: int,
    dry_run: bool,
) -> tuple[list[str], int]:
    cur = conn.execute(
        "SELECT monster_id, COUNT(*) FROM monsters_instances WHERE year = ? GROUP BY monster_id",
        (year,),
    )
    existing_counts = {row[0]: int(row[1]) for row in cur.fetchall()}

    cur = conn.execute(
        "SELECT x, y FROM monsters_instances WHERE year = ?",
        (year,),
    )
    occupied = {(int(row[0]), int(row[1])) for row in cur.fetchall()}

    eligible: list[tuple[MonsterTemplate, int]] = []
    for template in templates:
        if not template.spawnable:
            continue
        if template.spawn_years and year not in template.spawn_years:
            continue
        current = existing_counts.get(template.monster_id, 0)
        missing = max(0, per_monster - current)
        if missing <= 0:
            continue
        eligible.append((template, missing))

    if not eligible or per_monster <= 0:
        return [], 0

    total_spawns = sum(missing for _, missing in eligible)
    positions = _plan_positions(
        total_spawns, center_x, center_y, radius, blocked=occupied
    )
    created_at = int(time.time() * 1000)

    spawned_ids: list[str] = []
    pos_index = 0
    rng = random.Random(f"{year}:{len(eligible)}:{per_monster}")

    for template, missing in eligible:
        ions_min = int(template.ions_min or 0)
        ions_max = int(template.ions_max or template.ions_min or 0)
        if ions_max < ions_min:
            ions_max = ions_min
        rib_min = int(template.riblets_min or 0)
        rib_max = int(template.riblets_max or template.riblets_min or 0)
        if rib_max < rib_min:
            rib_max = rib_min

        for _ in range(missing):
            if pos_index >= len(positions):
                raise RuntimeError("ran out of coordinates while spawning monsters")
            x, y = positions[pos_index]
            pos_index += 1

            ions = rng.randint(ions_min, ions_max) if ions_max >= ions_min else ions_min
            riblets = rng.randint(rib_min, rib_max) if rib_max >= rib_min else rib_min

            instance_id = f"{template.monster_id}#{uuid.uuid4().hex[:8]}"

            minted_inventory = _mint_items(
                conn,
                template.starter_items,
                owner=instance_id,
                year=year,
                x=x,
                y=y,
                created_at=created_at,
                dry_run=dry_run,
            )
            minted_armour = _mint_items(
                conn,
                template.starter_armour,
                owner=instance_id,
                year=year,
                x=x,
                y=y,
                created_at=created_at,
                dry_run=dry_run,
            )

            armour_iid = minted_armour[0][1] if minted_armour else None
            payload = _build_monster_payload(
                template,
                instance_id,
                year=year,
                x=x,
                y=y,
                ions=ions,
                riblets=riblets,
                inventory=[*minted_inventory, *minted_armour],
                armour_iid=armour_iid,
            )

            stats_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            if not dry_run:
                conn.execute(
                    """
                    INSERT INTO monsters_instances (
                        instance_id, monster_id, year, x, y, hp_cur, hp_max, stats_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        instance_id,
                        template.monster_id,
                        year,
                        x,
                        y,
                        template.hp_max,
                        template.hp_max,
                        stats_json,
                        created_at,
                    ),
                )
            spawned_ids.append(instance_id)
    return spawned_ids, len(eligible)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed passive monster spawns")
    parser.add_argument("--db", required=True, help="Path to the SQLite database")
    parser.add_argument(
        "--years",
        help=(
            "Comma-separated list of years or ranges (e.g. 2000,2100-2300:50). "
            "If omitted the list is discovered automatically."
        ),
    )
    parser.add_argument(
        "--per-monster",
        type=int,
        default=4,
        help="Number of instances to spawn per monster template",
    )
    parser.add_argument("--center-x", type=int, default=0, help="Spawn center X coordinate")
    parser.add_argument("--center-y", type=int, default=0, help="Spawn center Y coordinate")
    parser.add_argument(
        "--radius",
        type=int,
        default=8,
        help="Radius around the center used for spawn placement",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without writing to the database",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        _ensure_tables(conn)

        try:
            templates = _fetch_templates(conn)
        except sqlite3.Error as exc:
            print(f"error: unable to load catalog: {exc}", file=sys.stderr)
            return 1

        if not templates:
            print("No monsters found in catalog; skipping spawn")
            return 0

        target_per_monster = max(0, args.per_monster)
        set_cli_years_override(args.years)
        years = get_world_years(db_path)
        if not years:
            print("No world years resolved; nothing to spawn.")
            return 0

        total_spawned = 0
        any_errors = False
        for year in years:
            try:
                spawned, monster_count = _spawn_monsters(
                    conn,
                    templates,
                    year=year,
                    per_monster=target_per_monster,
                    center_x=args.center_x,
                    center_y=args.center_y,
                    radius=max(1, args.radius),
                    dry_run=args.dry_run,
                )
            except Exception as exc:  # pragma: no cover - defensive path
                print(f"error: failed to spawn monsters for year {year}: {exc}", file=sys.stderr)
                any_errors = True
                break

            spawned_count = len(spawned)
            total_spawned += spawned_count
            if spawned_count > 0:
                print(
                    f"year={year}: spawned {spawned_count} (topped to {target_per_monster} each) "
                    f"for {monster_count} monsters."
                )
            else:
                print(
                    f"year={year}: nothing to spawn; already at {target_per_monster} each."
                )

        if any_errors:
            return 1

        if args.dry_run:
            print(
                f"Dry run complete. Would spawn {total_spawned} monsters across {len(years)} year(s)."
            )
            return 0

        if total_spawned > 0:
            conn.commit()
            print(
                f"Spawned {total_spawned} monster instance(s) across {len(years)} year(s) at {db_path}"
            )
        else:
            print("No monsters spawned; database already at target counts.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
