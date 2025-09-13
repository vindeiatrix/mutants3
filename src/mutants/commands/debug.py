from __future__ import annotations
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


def debug_cmd(arg: str, ctx):
    parts = arg.strip().split()
    bus = ctx["feedback_bus"]
    if len(parts) >= 3 and parts[0] == "add" and parts[1] == "item":
        from mutants.registries import items_catalog

        item_id = parts[2]
        catalog = items_catalog.load_catalog()
        if not catalog.get(item_id):
            bus.push("SYSTEM/WARN", f"Unknown item: {item_id}")
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
