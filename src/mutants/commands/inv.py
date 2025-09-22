from __future__ import annotations
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate
from mutants.services.items_weight import get_effective_weight
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
    """Resolve the effective weight for an item instance."""

    weight = get_effective_weight(inst, tpl)
    return _coerce_weight(weight)


def inv_cmd(arg: str, ctx):
    state, player = pstate.get_active_pair()
    pstate.bind_inventory_to_active_class(player)
    inv = [str(i) for i in (player.get("inventory") or []) if i]
    equipped = pstate.get_equipped_armour_id(state)
    if not equipped:
        equipped = pstate.get_equipped_armour_id(player)
    if equipped:
        inv = [iid for iid in inv if iid != equipped]
    cat = items_catalog.load_catalog()
    names = []
    total_weight = 0

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
            total_weight += max(0, weight)

    numbered = number_duplicates(names)
    display = [harden_final_display(with_article(n)) for n in numbered]
    bus = ctx["feedback_bus"]
    # Header must read exactly as specified; note the two spaces before '('
    bus.push(
        "SYSTEM/OK",
        f"You are carrying the following items:  (Total Weight: {total_weight} LB's)",
    )
    if not display:
        bus.push("SYSTEM/OK", "Nothing.")
        return
    for ln in uwrap.wrap_list(display):
        bus.push("SYSTEM/OK", ln)


def register(dispatch, ctx) -> None:
    dispatch.register("inv", lambda arg: inv_cmd(arg, ctx))
    dispatch.alias("inventory", "inv")
