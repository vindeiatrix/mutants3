from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from mutants.state import state_path

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

    def list_spawnable(self, year: Optional[int] = None) -> List[Dict[str, Any]]:
        out = []
        for m in self._list:
            if not m.get("spawnable", True):
                continue
            if year is None:
                out.append(m)
            else:
                years = m.get("spawn_years", [2000, 3000])
                if len(years) == 2 and int(years[0]) <= int(year) <= int(years[1]):
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
    if not isinstance(m["spawn_years"], (list, tuple)) or len(m["spawn_years"]) != 2:
        raise ValueError("spawn_years must be [min_year, max_year]")
    ia = m["innate_attack"]
    for f in ("name","power_base","power_per_level"):
        if f not in ia:
            raise ValueError(f"innate_attack missing {f}")
    # ok

def load_monsters_catalog(path: Path | str = DEFAULT_CATALOG_PATH) -> MonstersCatalog:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Missing monsters catalog at {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "monsters" in data:
        monsters = data["monsters"]
    elif isinstance(data, list):
        monsters = data
    else:
        raise ValueError('catalog must be a list of monsters or {"monsters": [...]}')

    # Lightweight validation (DEV-friendly; raise on structural errors)
    for m in monsters:
        _validate_base_monster(m)

    return MonstersCatalog(monsters)
