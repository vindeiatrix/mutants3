import json
import sqlite3
from pathlib import Path

import pytest

from mutants.registries import monsters_catalog


@pytest.fixture()
def temp_catalog_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "state.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE monsters_catalog (
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
                created_at TEXT,
                updated_at TEXT
            )
            """
        )

        rows = [
            (
                "hinted",
                "Hinted Monster",
                3,
                24,
                12,
                json.dumps([2000, 2001]),
                1,
                "Beware the hint!",
                json.dumps({"str": 11, "int": 8, "wis": 7, "dex": 10, "con": 9, "cha": 6}),
                json.dumps(
                    {
                        "name": "Claw",
                        "power_base": 5,
                        "power_per_level": 1,
                        "line": "The hinted monster slashes you!",
                    }
                ),
                10,
                1,
                3,
                0,
                2,
                json.dumps(["Shout"]),
                json.dumps(["Patchwork Armour"]),
                json.dumps(["Hint Scroll"]),
                "",
                "",
            ),
            (
                "plain",
                "Plain Monster",
                2,
                18,
                10,
                json.dumps([2000]),
                1,
                "Just a monster.",
                json.dumps({"str": 9, "int": 7, "wis": 8, "dex": 9, "con": 8, "cha": 6}),
                json.dumps(
                    {
                        "name": "Swipe",
                        "power_base": 4,
                        "power_per_level": 1,
                        "line": "The plain monster swipes!",
                    }
                ),
                None,
                None,
                None,
                None,
                None,
                json.dumps([]),
                json.dumps([]),
                json.dumps([]),
                "",
                "",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO monsters_catalog (
                monster_id, name, level, hp_max, armour_class, spawn_years,
                spawnable, taunt, stats_json, innate_attack_json, exp_bonus,
                ions_min, ions_max, riblets_min, riblets_max, spells_json,
                starter_armour_json, starter_items_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_load_monsters_catalog_reads_ai_overrides(monkeypatch: pytest.MonkeyPatch, temp_catalog_db: Path, tmp_path: Path) -> None:
    overrides_path = tmp_path / "catalog_overrides.json"
    overrides_path.write_text(
        json.dumps(
            [
                {
                    "monster_id": "hinted",
                    "metadata": {"notes": "custom"},
                    "ai_overrides": {
                        "prefers_ranged": True,
                        "wake": {"entry": 75, "look": 40},
                    },
                },
                {"monster_id": "plain"},
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(monsters_catalog, "DEFAULT_CATALOG_PATH", overrides_path)

    catalog = monsters_catalog.load_monsters_catalog(path=temp_catalog_db)

    hinted = catalog.require("hinted")
    assert hinted["metadata"] == {"notes": "custom"}
    assert hinted["ai_overrides"] == {
        "prefers_ranged": True,
        "wake": {"entry": 75, "look": 40},
    }

    plain = catalog.require("plain")
    assert plain["metadata"] == {}
    assert plain["ai_overrides"] is None
