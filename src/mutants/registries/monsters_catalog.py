from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from mutants.state import state_path

from .sqlite_store import SQLiteConnectionManager

DEFAULT_CATALOG_PATH = state_path("monsters", "catalog.json")

# EXP formula (can be adjusted later in one place)
def exp_for(level: int, exp_bonus: int = 0) -> int:
    return max(0, 100 * int(level) + int(exp_bonus))

class MonstersCatalog:
    """
    Read-only base monster definitions. Load once; fast lookups by monster_id.
    """
    def __init__(self, monsters: List[Dict[str, Any]]):
        self._list = monsters
        self._by_id: Dict[str, Dict[str, Any]] = {m["monster_id"]: m for m in monsters}

    def get(self, monster_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(monster_id)

    def require(self, monster_id: str) -> Dict[str, Any]:
        m = self.get(monster_id)
        if not m:
            raise KeyError(f"Unknown monster_id: {monster_id}")
        return m

    def _years_for_monster(self, monster: Dict[str, Any]) -> List[int]:
        years_raw = monster.get("spawn_years", [])
        years: List[int] = []
        if isinstance(years_raw, (list, tuple)):
            cleaned: List[int] = []
            for value in years_raw:
                try:
                    cleaned.append(int(value))
                except (TypeError, ValueError):
                    continue
            if len(cleaned) == 2 and cleaned[0] <= cleaned[1]:
                years = list(range(cleaned[0], cleaned[1] + 1))
            else:
                years = sorted(set(cleaned))
        return years

    def list_spawnable(self, year: Optional[int] = None) -> List[Dict[str, Any]]:
        out = []
        for m in self._list:
            if not m.get("spawnable", True):
                continue
            if year is None:
                out.append(m)
            else:
                years = self._years_for_monster(m)
                if year in years:
                    out.append(m)
        return out

def _validate_base_monster(m: Dict[str, Any]) -> None:
    """Lightweight checks (no external deps). Raises ValueError on obvious issues."""
    req_fields = ["monster_id","name","stats","hp_max","armour_class","level",
                  "innate_attack","spawn_years","spawnable","taunt"]
    for f in req_fields:
        if f not in m:
            raise ValueError(f"monster missing required field: {f}")
    stats = m["stats"]
    for a in ("str","int","wis","dex","con","cha"):
        if a not in stats:
            raise ValueError(f"stats missing {a}")
    years = m.get("spawn_years")
    if not isinstance(years, (list, tuple)) or not years:
        raise ValueError("spawn_years must be a non-empty list")
    coerced = []
    for value in years:
        try:
            coerced.append(int(value))
        except (TypeError, ValueError):
            raise ValueError("spawn_years entries must be integers") from None
    if len(coerced) == 2 and coerced[0] <= coerced[1]:
        pass
    elif len(set(coerced)) != len(coerced):
        raise ValueError("spawn_years list must not contain duplicates")
    ia = m["innate_attack"]
    for f in ("name","power_base","power_per_level"):
        if f not in ia:
            raise ValueError(f"innate_attack missing {f}")
    # ok

def _load_monsters_from_store(manager: SQLiteConnectionManager) -> List[Dict[str, Any]]:
    conn = manager.connect()
    cur = conn.execute(
        "SELECT monster_id, data_json FROM monsters_catalog ORDER BY monster_id ASC"
    )
    rows = cur.fetchall()
    if not rows:
        raise FileNotFoundError(
            f"Missing monsters catalog entries in SQLite store at {manager.path}"
        )

    monsters: List[Dict[str, Any]] = []
    for row in rows:
        raw = row["data_json"]
        if not isinstance(raw, str):
            raise ValueError(
                f"monsters_catalog row {row['monster_id']} missing JSON payload"
            )
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(
                "monsters_catalog rows must decode to JSON objects (dicts)"
            )
        data.setdefault("monster_id", row["monster_id"])
        monsters.append(data)
    return monsters


def load_monsters_catalog(path: Path | str | None = None) -> MonstersCatalog:
    manager = SQLiteConnectionManager(path) if path is not None else SQLiteConnectionManager()
    monsters = _load_monsters_from_store(manager)

    # Lightweight validation (DEV-friendly; raise on structural errors)
    for m in monsters:
        _validate_base_monster(m)

    return MonstersCatalog(monsters)
