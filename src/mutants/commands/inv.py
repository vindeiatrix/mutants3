from __future__ import annotations

from typing import Any, Dict, Optional

from mutants.ui.inventory_final import render_inventory_final


def _player_dict(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    state_mgr = ctx.get("state_manager")
    if state_mgr is None:
        return None
    try:
        active = state_mgr.get_active()
    except Exception:
        return None
    if active is None:
        return None
    if hasattr(active, "to_dict"):
        try:
            data = active.to_dict() or {}
            if isinstance(data, dict):
                return data
        except Exception:
            return None
    if isinstance(active, dict):
        return active
    return None


def inv_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    bus = ctx.get("feedback_bus")
    if bus is None:
        return

    player = _player_dict(ctx)
    if player is None:
        bus.push("SYSTEM/WARN", "Inventory unavailable.")
        return

    items = ctx.get("items")
    lines, total = render_inventory_final(player, items)

    bus.push(
        "SYSTEM/OK",
        f"You are carrying the following items:  (Total Weight: {total} LB's)",
    )
    for ln in lines:
        bus.push("SYSTEM/OK", ln)


def register(dispatch, ctx) -> None:
    dispatch.register("inv", lambda arg: inv_cmd(arg, ctx))
    dispatch.alias("inventory", "inv")
