from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from mutants.services.monster_entities import DEFAULT_INNATE_ATTACK_LINE
from mutants.state import state_path

from .sqlite_store import SQLiteConnectionManager


logger = logging.getLogger(__name__)


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

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
    for f in ("name","power_base","power_per_level","line"):
        if f not in ia:
            raise ValueError(f"innate_attack missing {f}")
    line_value = ia.get("line")
    if not isinstance(line_value, str) or not line_value.strip():
        raise ValueError("innate_attack line must be a non-empty string")
    # ok

def _load_catalog_overrides(path: Path | str | None) -> Dict[str, Dict[str, Any]]:
    """Return optional metadata/AI overrides from the JSON catalog file."""

    if path is None:
        return {}

    try:
        candidate = Path(path)
    except TypeError:
        return {}

    try:
        if not candidate.exists():
            return {}
    except OSError as exc:
        logger.warning("Failed to stat catalog overrides at %s: %s", candidate, exc)
        return {}

    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("Failed to read catalog overrides at %s: %s", candidate, exc)
        return {}
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON in catalog overrides at %s: %s", candidate, exc)
        return {}

    def _iter_entries(data: Any) -> Iterable[Mapping[str, Any]]:
        if isinstance(data, Mapping):
            for key, value in data.items():
                if isinstance(value, Mapping):
                    augmented = dict(value)
                    augmented.setdefault("monster_id", key)
                    yield augmented
            return
        if isinstance(data, list | tuple):
            for entry in data:
                if isinstance(entry, Mapping):
                    yield entry
            return

    overrides: Dict[str, Dict[str, Any]] = {}
    for entry in _iter_entries(payload):
        monster_id = str(entry.get("monster_id") or "").strip()
        if not monster_id:
            continue

        data: Dict[str, Any] = {}

        metadata = entry.get("metadata")
        if isinstance(metadata, Mapping):
            data["metadata"] = dict(metadata)

        ai_overrides = entry.get("ai_overrides")
        if isinstance(ai_overrides, Mapping):
            data["ai_overrides"] = dict(ai_overrides)

        if data:
            overrides[monster_id] = data

    return overrides


def _load_monsters_from_store(manager: SQLiteConnectionManager) -> List[Dict[str, Any]]:
    conn = manager.connect()
    columns = (
        "monster_id, name, level, hp_max, armour_class, spawn_years, spawnable, "
        "taunt, stats_json, innate_attack_json, exp_bonus, ions_min, ions_max, "
        "riblets_min, riblets_max, spells_json, starter_armour_json, starter_items_json"
    )
    cur = conn.execute(
        f"SELECT {columns} FROM monsters_catalog ORDER BY monster_id ASC"
    )
    rows = cur.fetchall()
    if not rows:
        raise FileNotFoundError(
            f"Missing monsters catalog entries in SQLite store at {manager.path}"
        )

    def _json_or(default: Any, raw: Any) -> Any:
        if isinstance(raw, str) and raw.strip():
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                return default
            if isinstance(value, type(default)):
                return value
        return default

    overrides = _load_catalog_overrides(DEFAULT_CATALOG_PATH)
    monsters: List[Dict[str, Any]] = []
    for row in rows:
        row_data = dict(row)

        spawn_years_raw = _json_or([], row_data.get("spawn_years"))
        spawn_years = []
        for value in spawn_years_raw:
            try:
                spawn_years.append(int(value))
            except (TypeError, ValueError):
                continue

        stats = _json_or({}, row_data.get("stats_json"))
        innate = _json_or({}, row_data.get("innate_attack_json"))
        spells = _json_or([], row_data.get("spells_json"))
        spells = [str(item) for item in spells if item not in (None, "")]
        starter_armour = _json_or([], row_data.get("starter_armour_json"))
        starter_armour = [str(item) for item in starter_armour if item not in (None, "")]
        starter_items = _json_or([], row_data.get("starter_items_json"))
        starter_items = [str(item) for item in starter_items if item not in (None, "")]

        monster = {
            "monster_id": row_data.get("monster_id"),
            "name": row_data.get("name") or "",
            "level": int(row_data.get("level") or 0),
            "hp_max": int(row_data.get("hp_max") or 0),
            "armour_class": int(row_data.get("armour_class") or 0),
            "spawn_years": spawn_years,
            "spawnable": bool(int(row_data.get("spawnable") or 0)),
            "taunt": row_data.get("taunt") or "",
            "stats": stats if isinstance(stats, dict) else {},
            "innate_attack": innate if isinstance(innate, dict) else {},
            "exp_bonus": _optional_int(row_data.get("exp_bonus")),
            "ions_min": _optional_int(row_data.get("ions_min")),
            "ions_max": _optional_int(row_data.get("ions_max")),
            "riblets_min": _optional_int(row_data.get("riblets_min")),
            "riblets_max": _optional_int(row_data.get("riblets_max")),
            "spells": spells,
            "starter_armour": starter_armour,
            "starter_items": starter_items,
        }

        innate_payload = monster.get("innate_attack")
        if isinstance(innate_payload, dict):
            line_value = innate_payload.get("line")
            if not isinstance(line_value, str) or not line_value.strip():
                innate_payload["line"] = DEFAULT_INNATE_ATTACK_LINE

        override_payload = overrides.get(str(monster.get("monster_id") or ""))
        if override_payload is None:
            monster["metadata"] = {}
            monster["ai_overrides"] = None
        else:
            metadata = override_payload.get("metadata")
            monster["metadata"] = dict(metadata) if isinstance(metadata, Mapping) else {}

            ai_overrides = override_payload.get("ai_overrides")
            monster["ai_overrides"] = dict(ai_overrides) if isinstance(ai_overrides, Mapping) else None

        monsters.append(monster)
    return monsters


def load_monsters_catalog(path: Path | str | None = None) -> MonstersCatalog:
    manager = SQLiteConnectionManager(path) if path is not None else SQLiteConnectionManager()
    monsters = _load_monsters_from_store(manager)

    # Lightweight validation (DEV-friendly; raise on structural errors)
    for m in monsters:
        _validate_base_monster(m)

    return MonstersCatalog(monsters)
