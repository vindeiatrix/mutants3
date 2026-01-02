from __future__ import annotations
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate
from mutants.services.items_weight import get_effective_weight
from ..ui import styles as st
from ..ui import groups as UG
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
    raw_inv = [str(i) for i in (player.get("inventory") or []) if i]
    # Drop any dangling instance ids that no longer exist in the registry to
    # avoid showing phantom items (e.g., after conversion failures).
    inv: list[str] = []
    dangling: list[str] = []
    for iid in raw_inv:
        if itemsreg.get_instance(iid):
            inv.append(iid)
        else:
            dangling.append(iid)

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
        tpl_id = None
        tpl = {}
        if inst:
            tpl_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
            tpl = cat.get(str(tpl_id)) if tpl_id else {}
            if not tpl:
                try:
                    tpl = items_catalog.catalog_defaults(str(tpl_id))
                except Exception:
                    tpl = {}
            names.append(item_label(inst, tpl or {}, show_charges=False))
        else:
            tpl = cat.get(str(iid)) if cat else {}
            if not tpl:
                try:
                    tpl = items_catalog.catalog_defaults(str(iid))
                except Exception:
                    tpl = {}
            if tpl:
                names.append(item_label({"item_id": str(iid)}, tpl or {}, show_charges=False))
            else:
                names.append(str(iid))

        weight = _resolve_weight(inst, tpl or {})
        if weight is not None:
            total_weight += max(0, weight)

    if dangling:
        try:
            cls = pstate.get_active_class(state)
            pstate.update_player_inventory(state, cls, inv)
            pstate.save_state(state, reason="inv.prune_dangling")
            if isinstance(ctx, dict):
                ctx["player_state"] = state
                ctx.pop(pstate._RUNTIME_PLAYER_KEY, None)  # type: ignore[attr-defined]
                refreshed = pstate.ensure_player_state(ctx)
                if isinstance(refreshed, dict):
                    refreshed["inventory"] = list(inv)
                    refreshed["_dirty"] = False
        except Exception:
            # If cleanup fails, continue rendering without crashing the command.
            pass

    numbered = number_duplicates(names)
    display = [harden_final_display(with_article(n)) for n in numbered]
    bus = ctx["feedback_bus"]
    header = st.colorize_text(
        f"You are carrying the following items:  (Total Weight: {total_weight} LB's)",
        group=UG.HEADER,
    )
    body_lines = []
    if not display:
        body_lines.append("Nothing.")
    else:
        for ln in uwrap.wrap_list(display):
            body_lines.append(st.colorize_text(ln, group=UG.LOG_LINE))
    block = "\n".join([header, *body_lines])
    bus.push("SYSTEM/OK", block)


def register(dispatch, ctx) -> None:
    dispatch.register("inv", lambda arg: inv_cmd(arg, ctx))
    dispatch.alias("inventory", "inv")
