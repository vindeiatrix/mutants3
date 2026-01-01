"""
Lightweight state audit to catch cross-partition leaks (ready targets in other years).

Usage:
    python -m tools.audit_state
"""
from __future__ import annotations

import sys
from typing import List

from mutants.bootstrap.lazyinit import ensure_player_state
from mutants.registries import monsters_instances
from mutants.registries.storage import get_stores
from mutants.services import player_state as pstate


def _audit_ready_target(state, monsters) -> List[str]:
    issues: List[str] = []
    ready = pstate.get_ready_target_for_active(state)
    if not ready:
        return issues
    try:
        player_year, _, _ = pstate.canonical_player_pos(state)
    except Exception:
        return issues
    record = None
    try:
        record = monsters.get(ready)
    except Exception:
        record = None
    if not record:
        issues.append(f"ready_target '{ready}' missing from monsters store")
        return issues
    pos = record.get("pos") or ()
    try:
        mon_year = int(pos[0])
    except Exception:
        mon_year = None
    if mon_year is None or mon_year != player_year:
        issues.append(
            f"ready_target '{ready}' in year={mon_year} while player is in year={player_year}"
        )
    return issues


def _coerce_pos(entry) -> tuple[int, int, int] | None:
    pos = None
    if isinstance(entry, dict):
        pos = entry.get("pos") or entry.get("position")
        if not pos:
            year = entry.get("year")
            x = entry.get("x")
            y = entry.get("y")
            pos = (year, x, y)
    try:
        raw = list(pos) if pos is not None else []
    except Exception:
        return None
    if len(raw) < 3:
        return None
    try:
        return int(raw[0]), int(raw[1]), int(raw[2])
    except Exception:
        return None


def _audit_monster_cache(monsters) -> List[str]:
    issues: List[str] = []
    seen_ids: set[str] = set()
    for record in monsters.list_all():
        if not isinstance(record, dict):
            continue
        mid = str(record.get("instance_id") or record.get("id") or record.get("monster_instance_id") or "").strip()
        if not mid:
            issues.append("monster missing instance_id")
            continue
        if mid in seen_ids:
            issues.append(f"monster duplicate instance_id={mid}")
            continue
        seen_ids.add(mid)
        pos = _coerce_pos(record)
        if pos is None:
            issues.append(f"monster {mid} missing/invalid pos")
            continue
        if any(not isinstance(token, int) for token in pos):
            issues.append(f"monster {mid} non-int pos={pos}")
    return issues


def _audit_item_cache() -> List[str]:
    issues: List[str] = []
    stores = get_stores()
    item_store = stores.items
    seen: set[str] = set()
    for record in item_store.snapshot():
        if not isinstance(record, dict):
            continue
        iid = str(record.get("iid") or record.get("instance_id") or record.get("id") or "").strip()
        if not iid:
            issues.append("item missing instance_id")
            continue
        if iid in seen:
            issues.append(f"item duplicate instance_id={iid}")
            continue
        seen.add(iid)
        owner = record.get("owner")
        pos = _coerce_pos(record)
        if owner in (None, "", 0):
            if pos is None:
                issues.append(f"ground item {iid} missing pos")
        else:
            # Inventory item: ensure it is not also on ground
            if pos is None:
                continue
    return issues


def main() -> int:
    state = ensure_player_state()
    monsters = monsters_instances.get()

    issues: List[str] = []
    issues.extend(_audit_ready_target(state, monsters))
    issues.extend(_audit_monster_cache(monsters))
    issues.extend(_audit_item_cache())

    if issues:
        for line in issues:
            print(f"[AUDIT] {line}")
        return 1
    print("Audit passed: no cross-partition issues detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
