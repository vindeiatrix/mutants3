from __future__ import annotations
import json, os
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.ui.inventory_section import render_inventory_section


def _player_file() -> str:
    return os.path.join(os.getcwd(), "state", "playerlivestate.json")


def _load_player():
    try:
        return json.load(open(_player_file(), "r", encoding="utf-8"))
    except FileNotFoundError:
        return {}


def inv_cmd(arg: str, ctx):
    p = _load_player()
    inv = list(p.get("inventory") or [])
    bus = ctx["feedback_bus"]
    if isinstance(ctx, dict):
        render_ctx = dict(ctx)
    else:
        render_ctx = {}
    render_ctx.setdefault("items_catalog_loader", items_catalog.load_catalog)
    render_ctx.setdefault("items_instance_resolver", itemsreg.get_instance)

    lines = render_inventory_section(render_ctx, inv)
    for line in lines:
        bus.push("SYSTEM/OK", line)


def register(dispatch, ctx) -> None:
    dispatch.register("inv", lambda arg: inv_cmd(arg, ctx))
    dispatch.alias("inventory", "inv")
