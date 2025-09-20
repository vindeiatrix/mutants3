from __future__ import annotations

from typing import Dict
from collections.abc import Mapping

from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate
from mutants.services.combat_calc import (
    armour_class_for_active,
    armour_class_from_equipped,
    dex_bonus_for_active,
)
from mutants.ui.item_display import item_label

from . import inv as inv_cmd_mod


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def statistics_cmd(arg: str, ctx) -> None:
    state, active = pstate.get_active_pair()
    player: Dict[str, object] = active if isinstance(active, dict) else {}
    bus = ctx["feedback_bus"]

    name = player.get("name", "Unknown")
    cls = player.get("class", "Unknown")
    stats_map = pstate.get_stats_for_active(state)
    STR = _int(stats_map.get("str"))
    INT = _int(stats_map.get("int"))
    WIS = _int(stats_map.get("wis"))
    DEX = _int(stats_map.get("dex"))
    CON = _int(stats_map.get("con"))
    CHA = _int(stats_map.get("cha"))

    pos = player.get("pos")
    if isinstance(pos, (list, tuple)) and pos:
        year = _int(pos[0], default=2000)
    else:
        year = 2000

    exhaustion = pstate.get_exhaustion_for_active(state)
    hp = pstate.get_hp_for_active(state)
    hp_cur = _int(hp.get("current"))
    hp_max = _int(hp.get("max"))
    exp_pts = pstate.get_exp_for_active(state)
    level = pstate.get_level_for_active(state)
    riblets = pstate.get_riblets_for_active(state)
    ions = pstate.get_ions_for_active(state)

    cat = items_catalog.load_catalog()
    armour_iid = pstate.get_equipped_armour_id(state)
    armour_status = "None"
    if armour_iid:
        inst = itemsreg.get_instance(armour_iid)
        if inst:
            tpl_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
            tpl = cat.get(str(tpl_id)) if tpl_id and cat else {}
            armour_status = item_label(inst, tpl or {}, show_charges=False)
        else:
            armour_status = str(armour_iid)
    else:
        armour = player.get("armour")
        if isinstance(armour, Mapping):
            wearing = armour.get("wearing")
            if wearing is not None:
                armour_status = str(wearing)

    bus.push("SYSTEM/OK", f"Name: {name} / Mutant {cls}")
    bus.push("SYSTEM/OK", f"Exhaustion : {exhaustion}")

    bus.push("SYSTEM/OK", f"Str: {STR:>3}    Int: {INT:>3}   Wis: {WIS:>3}")
    bus.push("SYSTEM/OK", f"Dex: {DEX:>3}    Con: {CON:>3}   Cha: {CHA:>3}")

    bus.push("SYSTEM/OK", f"Hit Points  : {hp_cur} / {hp_max}")
    bus.push("SYSTEM/OK", f"Exp. Points : {exp_pts:<6} Level: {level}")
    bus.push("SYSTEM/OK", f"Riblets     : {riblets}")
    bus.push("SYSTEM/OK", f"Ions        : {ions}")
    armour_class = armour_class_for_active(state)
    dex_bonus = dex_bonus_for_active(state)
    armour_bonus = armour_class_from_equipped(state)
    bus.push(
        "SYSTEM/OK",
        "Wearing Armor : "
        f"{armour_status}  Armour Class: {armour_class}  "
        f"(Dex bonus: +{dex_bonus}, Armour: +{armour_bonus})",
    )
    bus.push("SYSTEM/OK", "Ready to Combat: NO ONE")
    bus.push("SYSTEM/OK", "Readied Spell  : No spell memorized.")
    bus.push("SYSTEM/OK", f"Year A.D. : {year}")
    bus.push("SYSTEM/OK", "")

    inv_cmd_mod.inv_cmd("", ctx)


def register(dispatch, ctx) -> None:
    dispatch.register("statistics", lambda arg: statistics_cmd(arg, ctx))
    for alias in ["sta", "stat", "stati", "statis", "statist", "statisti", "statistic"]:
        dispatch.alias(alias, "statistics")
