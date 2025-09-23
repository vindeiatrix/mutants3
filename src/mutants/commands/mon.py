from __future__ import annotations

import shlex
from collections.abc import Iterable as IterableABC
from typing import Any, Dict, Iterable, Mapping, Tuple


_MON_STAT_KEYS: Tuple[str, ...] = ("str", "dex", "con", "int", "wis", "cha")


def _normalize_monster_lookup(monsters: Any, token: str) -> Tuple[Mapping[str, Any] | None, Iterable[str]]:
    if monsters is None or not token:
        return None, []

    lookup = getattr(monsters, "get", None)
    if callable(lookup):
        monster = lookup(token)
        if isinstance(monster, Mapping):
            return monster, []

    matches: list[str] = []
    candidates = getattr(monsters, "list_all", None)
    if callable(candidates):
        try:
            for entry in candidates():
                if not isinstance(entry, Mapping):
                    continue
                mid = str(entry.get("id") or "")
                name = str(entry.get("name") or "")
                token_lower = token.lower()
                if mid == token:
                    return entry, []
                if mid.startswith(token) or name.lower().startswith(token_lower):
                    matches.append(mid)
        except Exception:
            return None, []
    return None, matches


def _format_stats(stats: Mapping[str, Any] | None) -> str:
    if not isinstance(stats, Mapping):
        return "-"
    parts = []
    for key in _MON_STAT_KEYS:
        value = stats.get(key)
        try:
            value_int = int(value)
        except (TypeError, ValueError):
            continue
        parts.append(f"{key}:{value_int}")
    return ",".join(parts) if parts else "-"


def _format_hp(hp: Mapping[str, Any] | None) -> str:
    if not isinstance(hp, Mapping):
        return "?/?"
    cur = hp.get("current")
    cap = hp.get("max")
    return f"{cur}/{cap}"


def _format_armour(armour: Mapping[str, Any] | None) -> str:
    if not isinstance(armour, Mapping):
        return "-"
    item_id = armour.get("item_id") or armour.get("iid")
    return str(item_id) if item_id else "-"


def _bag_count(bag: Any) -> int:
    if not isinstance(bag, list):
        return 0
    count = 0
    for entry in bag:
        if isinstance(entry, Mapping):
            count += 1
    return count


def _summarize_monster(monster: Mapping[str, Any]) -> str:
    monster_id = monster.get("id") or "?"
    name = monster.get("name") or "?"
    level = monster.get("level")
    stats_text = _format_stats(monster.get("stats"))
    hp_text = _format_hp(monster.get("hp"))
    pinned = monster.get("pinned_years")
    if isinstance(pinned, IterableABC) and not isinstance(pinned, (str, bytes)):
        pinned_text = ",".join(str(year) for year in pinned) or "-"
    else:
        pinned_text = "-"
    wielded = monster.get("wielded") or "-"
    armour_text = _format_armour(monster.get("armour_slot"))
    bag_items = _bag_count(monster.get("bag"))
    return (
        f"MON id={monster_id} name={name} level={level} hp={hp_text} stats={stats_text} "
        f"pinned={pinned_text or '-'} wielded={wielded} armour={armour_text} bag={bag_items}"
    )


def mon_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    parts = shlex.split((arg or "").strip())
    bus = ctx["feedback_bus"]
    if not parts:
        bus.push("SYSTEM/INFO", "Usage: mon debug <monster_id>")
        return

    if parts[0].lower() in {"debug", "info", "show"}:
        parts = parts[1:]
        if not parts:
            bus.push("SYSTEM/INFO", "Usage: mon debug <monster_id>")
            return

    token = parts[0]
    monster_state = ctx.get("monsters")
    monster, matches = _normalize_monster_lookup(monster_state, token)
    if matches:
        preview = ", ".join(sorted(matches)[:5])
        bus.push("SYSTEM/WARN", f'Ambiguous monster "{token}" (matches: {preview})')
        return
    if not monster:
        bus.push("SYSTEM/WARN", f"Unknown monster '{token}'.")
        return

    summary = _summarize_monster(monster)
    bus.push("DEBUG", summary)


def register(dispatch, ctx) -> None:
    dispatch.register("mon", lambda arg: mon_cmd(arg, ctx))
