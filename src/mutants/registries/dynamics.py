from __future__ import annotations
import json, os, time
from typing import Dict, Optional

ROOT = os.getcwd()
PATH = os.path.join(ROOT, "state", "world", "dynamics.json")


def _load() -> Dict[str, Dict]:
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save(data: Dict[str, Dict]) -> None:
    tmp = PATH + ".tmp"
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
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
