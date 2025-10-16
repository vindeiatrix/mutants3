from __future__ import annotations

import sqlite3

from mutants.registries.sqlite_store import SQLiteConnectionManager


def test_migration_adds_combat_state_columns() -> None:
    manager = SQLiteConnectionManager(db_path=":memory:")
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE schema_meta (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_meta(version) VALUES (5)")
        conn.execute(
            """
            CREATE TABLE monsters_instances (
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
            INSERT INTO monsters_instances (
                instance_id, monster_id, year, x, y, hp_cur, hp_max, stats_json, created_at
            ) VALUES ('abc', 'goblin', 2000, 1, 2, 5, 10, '{}', 1234567890)
            """
        )
        conn.commit()

        manager._ensure_schema(conn)

        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(monsters_instances)").fetchall()
        }
        assert {
            "target_player_id",
            "ai_state_json",
            "bag_json",
            "timers_json",
        }.issubset(columns)

        row = conn.execute(
            "SELECT target_player_id, ai_state_json, bag_json, timers_json FROM monsters_instances"
        ).fetchone()
        assert row == (None, None, None, None)

        index_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='monsters_target_idx'"
        ).fetchone()
        assert index_row is not None

        version_row = conn.execute("SELECT version FROM schema_meta").fetchone()
        assert version_row[0] == 6
    finally:
        conn.close()
        manager.close()
