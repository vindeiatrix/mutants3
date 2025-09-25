from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional

from mutants.state import state_path
from mutants.util.directions import DELTA as _DELTA, OPP as _OPP

PATH = state_path("world", "dynamics.json")


def _load() -> Dict[str, Dict]:
    try:
        with PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save(data: Dict[str, Dict]) -> None:
    tmp = PATH.with_name(PATH.name + ".tmp")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PATH)


def _key(year: int, x: int, y: int, dir_key: str) -> str:
    return f"{year}:{x}:{y}:{dir_key}"


def overlay_for(year: int, x: int, y: int, dir_key: str, now: Optional[int] = None) -> Optional[Dict]:
    now = now or int(time.time())
    data = _load()
    ov = data.get(_key(year, x, y, dir_key))
    if not ov:
        return None
    ttl = int(ov.get("ttl", 0))
    created = int(ov.get("created_at", now))
    if ttl > 0 and created + ttl < now:
        data.pop(_key(year, x, y, dir_key), None)
        _save(data)
        return None
    return ov


def set_barrier(year: int, x: int, y: int, dir_key: str, *, hard: bool = False, ttl: int = 0) -> None:
    data = _load()
    data[_key(year, x, y, dir_key)] = {
        "kind": "barrier",
        "hard": bool(hard),
        "ttl": int(ttl),
        "created_at": int(time.time()),
    }
    _save(data)


def set_blasted(year: int, x: int, y: int, dir_key: str, *, ttl: int = 0) -> None:
    data = _load()
    data[_key(year, x, y, dir_key)] = {
        "kind": "blasted",
        "ttl": int(ttl),
        "created_at": int(time.time()),
    }
    _save(data)


# --- gate locks --------------------------------------------------------------

def _lock_key(year: int, x: int, y: int, dir_key: str) -> str:
    return f"lock:{year}:{x}:{y}:{dir_key}"


def get_lock(year: int, x: int, y: int, dir_key: str) -> Optional[Dict]:
    data = _load()
    lk = data.get(_lock_key(year, x, y, dir_key))
    if isinstance(lk, dict) and lk.get("locked"):
        return lk
    return None


def set_lock(year: int, x: int, y: int, dir_key: str, lock_type: str) -> None:
    data = _load()
    key = _lock_key(year, x, y, dir_key)
    data[key] = {"locked": True, "lock_type": str(lock_type)}
    # Mirror to the neighbor edge so lock is enforced from both sides.
    dk = dir_key.lower()
    dx, dy = _DELTA.get(dk, (0, 0))
    opp = _OPP.get(dk, dk).upper()
    data[_lock_key(year, x + dx, y + dy, opp)] = {
        "locked": True,
        "lock_type": str(lock_type),
    }
    _save(data)


def clear_lock(year: int, x: int, y: int, dir_key: str) -> None:
    data = _load()
    dk = dir_key.lower()
    dx, dy = _DELTA.get(dk, (0, 0))
    opp = _OPP.get(dk, dk).upper()
    data.pop(_lock_key(year, x, y, dir_key), None)
    data.pop(_lock_key(year, x + dx, y + dy, opp), None)
    _save(data)
