from __future__ import annotations
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate
from ..ui.item_display import item_label, number_duplicates, with_article
from ..ui import wrap as uwrap
from ..ui.textutils import harden_final_display


def inv_cmd(arg: str, ctx):
    _, player = pstate.get_active_pair()
    inv = list(player.get("inventory") or [])
    cat = items_catalog.load_catalog()
    names = []
    for iid in inv:
        inst = itemsreg.get_instance(iid)
        if not inst:
            names.append(iid)
            continue
        tpl_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
        tpl = cat.get(str(tpl_id)) if tpl_id else {}
        names.append(item_label(inst, tpl or {}, show_charges=False))
    numbered = number_duplicates(names)
    display = [harden_final_display(with_article(n)) for n in numbered]
    bus = ctx["feedback_bus"]
    if not display:
        bus.push("SYSTEM/OK", "You are carrying nothing.")
        return
    bus.push("SYSTEM/OK", "You are carrying:")
    for ln in uwrap.wrap_list(display):
        bus.push("SYSTEM/OK", ln)


def register(dispatch, ctx) -> None:
    dispatch.register("inv", lambda arg: inv_cmd(arg, ctx))
    dispatch.alias("inventory", "inv")
