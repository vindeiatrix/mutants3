from __future__ import annotations
import json, os
from mutants.registries import items_catalog, items_instances as itemsreg
from ..ui.item_display import item_label, number_duplicates, with_article
from ..ui import wrap as uwrap
from ..ui.textutils import harden_final_display


def _total_weight(inst_tpl_pairs):
    total = 0.0
    for inst, tpl in inst_tpl_pairs:
        qty_raw = (inst or {}).get("quantity", 1)
        try:
            qty_val = float(qty_raw)
        except (TypeError, ValueError):
            qty_val = 1.0

        weight_raw = (tpl or {}).get("weight", 0)
        try:
            weight_val = float(weight_raw)
        except (TypeError, ValueError):
            weight_val = 0.0

        total += weight_val * qty_val
    return total


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
    cat = items_catalog.load_catalog()
    names = []
    inst_tpl_pairs = []
    for iid in inv:
        inst = itemsreg.get_instance(iid) or {}
        tpl = cat.get(inst.get("item_id")) or {}
        inst_tpl_pairs.append((inst, tpl))
        names.append(item_label(inst, tpl, show_charges=False))
    numbered = number_duplicates(names)
    display = [harden_final_display(with_article(n)) for n in numbered]
    bus = ctx["feedback_bus"]
    total_weight = _total_weight(inst_tpl_pairs)
    header = (
        f"You are carrying the following items: (Total Weight: {round(total_weight)} LB's)"
    )
    bus.push("SYSTEM/OK", header)
    if not display:
        bus.push("SYSTEM/OK", "Nothing.")
        return
    for ln in uwrap.wrap_list(display):
        bus.push("SYSTEM/OK", ln)


def register(dispatch, ctx) -> None:
    dispatch.register("inv", lambda arg: inv_cmd(arg, ctx))
    dispatch.alias("inventory", "inv")
