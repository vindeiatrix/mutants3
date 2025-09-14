from __future__ import annotations
import re, shlex

from ..registries import items_instances as itemsreg


def _pos_from_ctx(ctx) -> tuple[int, int, int]:
    state = ctx.get("player_state", {})
    aid = state.get("active_id")
    for pl in state.get("players", []):
        if pl.get("id") == aid:
            pos = pl.get("pos") or [0, 0, 0]
            return int(pos[0]), int(pos[1]), int(pos[2])
    pos = state.get("players", [{}])[0].get("pos") or [0, 0, 0]
    return int(pos[0]), int(pos[1]), int(pos[2])


def _normalize(s: str) -> str:
    s = s.strip().lower().strip("'\"")
    s = re.sub(r"^(a|an|the)\s+", "", s)
    return s


def _display_name(it: dict) -> str:
    for key in ("display_name", "name", "title"):
        if isinstance(it.get(key), str):
            return it[key]
    return it.get("item_id", "")


def _resolve_item_id(raw: str, catalog):
    q = _normalize(raw)
    q_id = q.replace("-", "_")
    if catalog.get(q_id):
        return q_id, None
    prefix = [iid for iid in catalog._by_id if iid.startswith(q_id)]
    if len(prefix) == 1:
        return prefix[0], None
    if len(prefix) > 1:
        return None, prefix
    name_matches = []
    for it in catalog._items_list:
        if _normalize(_display_name(it)) == q:
            name_matches.append(it["item_id"])
    if len(name_matches) == 1:
        return name_matches[0], None
    if len(name_matches) > 1:
        return None, name_matches
    return None, []


def debug_cmd(arg: str, ctx):
    parts = shlex.split(arg.strip())
    bus = ctx["feedback_bus"]
    if len(parts) >= 3 and parts[0] == "add" and parts[1] == "item":
        from mutants.registries import items_catalog

        catalog = items_catalog.load_catalog()
        item_arg = parts[2]
        item_id, matches = _resolve_item_id(item_arg, catalog)
        if not item_id:
            if matches:
                bus.push(
                    "SYSTEM/WARN",
                    f"Ambiguous item ID: \"{item_arg}\" matches {', '.join(matches)}.",
                )
            else:
                bus.push("SYSTEM/WARN", f"Unknown item: {item_arg}")
            return
        try:
            count = int(parts[3]) if len(parts) >= 4 else 1
        except Exception:
            count = 1
        year, x, y = _pos_from_ctx(ctx)
        for _ in range(max(1, count)):
            itemsreg.create_and_save_instance(item_id, year, x, y, origin="debug_add")
        bus.push("DEBUG", f"added {count} x {item_id} at ({x},{y}).")
        return
    bus.push("SYSTEM/INFO", "Usage: debug add item <item_id> [count]")


def register(dispatch, ctx) -> None:
    dispatch.register("debug", lambda arg: debug_cmd(arg, ctx))
