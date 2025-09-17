from __future__ import annotations
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate
from ..ui.item_display import item_label, number_duplicates, with_article
from ..ui import wrap as uwrap
from ..ui.textutils import harden_final_display


def _coerce_weight(value):
    """Return an integer weight or ``None`` when the value is unusable."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _resolve_weight(inst, tpl) -> int | None:
    """Resolve the weight for an item instance using overrides and catalog."""

    raw = inst.get("weight")
    if raw is None and tpl:
        for key in ("weight", "weight_lbs", "lbs"):
            if key in tpl:
                raw = tpl.get(key)
                if raw is not None:
                    break
    return _coerce_weight(raw)


def inv_cmd(arg: str, ctx):
    _, player = pstate.get_active_pair()
    inv = list(player.get("inventory") or [])
    cat = items_catalog.load_catalog()
    names = []
    total_weight = 0
    weight_known = False

    for iid in inv:
        inst = itemsreg.get_instance(iid)
        if not inst:
            names.append(str(iid))
            continue
        tpl_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
        tpl = cat.get(str(tpl_id)) if tpl_id else {}
        names.append(item_label(inst, tpl or {}, show_charges=False))

        weight = _resolve_weight(inst, tpl or {})
        if weight is not None:
            weight_known = True
            total_weight += weight

    numbered = number_duplicates(names)
    display = [harden_final_display(with_article(n)) for n in numbered]
    bus = ctx["feedback_bus"]
    if not display:
        bus.push("SYSTEM/OK", "You are carrying nothing.")
        return

    if weight_known:
        unit = "lb" if total_weight == 1 else "lbs"
        bus.push("SYSTEM/OK", f"You are carrying: (Total weight: {total_weight} {unit})")
    else:
        bus.push("SYSTEM/OK", "You are carrying:")
    for ln in uwrap.wrap_list(display):
        bus.push("SYSTEM/OK", ln)


def register(dispatch, ctx) -> None:
    dispatch.register("inv", lambda arg: inv_cmd(arg, ctx))
    dispatch.alias("inventory", "inv")
