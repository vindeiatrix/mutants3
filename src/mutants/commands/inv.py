from __future__ import annotations

from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services.inventory_source import get_player_inventory_instances
from mutants.ui.inventory_section import render_inventory_section


def inv_cmd(arg: str, ctx):
    bus = ctx["feedback_bus"]
    if isinstance(ctx, dict):
        render_ctx = dict(ctx)
    else:
        render_ctx = {}
    render_ctx.setdefault("items_catalog_loader", items_catalog.load_catalog)
    render_ctx.setdefault("items_instance_resolver", itemsreg.get_instance)

    inv_instances = get_player_inventory_instances(ctx)
    lines = render_inventory_section(render_ctx, inv_instances)
    for line in lines:
        bus.push("SYSTEM/OK", line)


def register(dispatch, ctx) -> None:
    dispatch.register("inv", lambda arg: inv_cmd(arg, ctx))
    dispatch.alias("inventory", "inv")
