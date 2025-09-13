from __future__ import annotations
from pathlib import Path
import json, time, difflib
from typing import Dict, Any, Tuple, Optional

# Reuse STATE from runtime so paths are consistent with the rest of the app.
try:
    from mutants.bootstrap.runtime import STATE
except Exception:
    STATE = Path("state")

_ITEMS_PATH = STATE / "items" / "catalog.json"
_CACHE: Dict[str, Any] = {}
_CACHE_MTIME: Optional[float] = None

def _load_raw() -> Dict[str, Any]:
    with _ITEMS_PATH.open() as f:
        return json.load(f)

def _normalize(s: str) -> str:
    return "".join(s.lower().split())

def _rebuild_index(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Expected catalog format examples:
      {"items": [{"id":"nuclear-waste","name":"Nuclear-Waste", ...}, ...]}
      or a dict keyed by id. We index both id and name.
    """
    items = []
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        items = data["items"]
    elif isinstance(data, dict):
        # fallback: dict keyed by id
        items = [{"id": k, **(v or {})} for k, v in data.items()]
    else:
        raise ValueError("Unrecognized items catalog format")

    index: Dict[str, Dict[str, Any]] = {}
    names: Dict[str, str] = {}
    for it in items:
        iid = str(it.get("id") or "").strip()
        name = str(it.get("name") or iid).strip()
        if not iid:
            continue
        for key in {iid, name}:
            if key:
                index[_normalize(key)] = it
        names[name] = iid
    return {"items": items, "index": index, "names": names}

def _ensure_cache() -> Dict[str, Any]:
    global _CACHE, _CACHE_MTIME
    mtime = _ITEMS_PATH.stat().st_mtime
    if _CACHE and _CACHE_MTIME == mtime:
        return _CACHE
    data = _load_raw()
    _CACHE = _rebuild_index(data)
    _CACHE_MTIME = mtime
    return _CACHE

def resolve_item(token: str) -> Tuple[Optional[Dict[str, Any]], list[str]]:
    """
    Resolve a user token to a catalog item. Returns (item_or_None, suggestions).
    - Exact match on id or name (case/space-insensitive) wins.
    - Else, unique prefix match on normalized keys.
    - Else, return suggestions using difflib on visible names.
    """
    token_norm = _normalize(token)
    cache = _ensure_cache()
    idx = cache["index"]
    if token_norm in idx:
        return idx[token_norm], []

    # Unique prefix over normalized keys
    candidates = [v for k, v in idx.items() if k.startswith(token_norm)]
    # Deduplicate same object references (id and name both index the same dict)
    uniq = []
    seen_ids = set()
    for c in candidates:
        cid = c.get("id")
        if cid not in seen_ids:
            seen_ids.add(cid)
            uniq.append(c)
    if len(uniq) == 1:
        return uniq[0], []

    # Suggestions: use pretty names (fallback to ids)
    names = list(cache["names"].keys())
    sug = difflib.get_close_matches(token, names, n=5, cutoff=0.6)
    if not sug:
        # also try IDs
        ids = [it.get("id", "") for it in cache["items"]]
        sug = difflib.get_close_matches(token, ids, n=5, cutoff=0.6)
    return None, sug
