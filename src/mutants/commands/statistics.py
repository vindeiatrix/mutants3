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
from mutants.ui import styles as st
from mutants.ui import groups as UG
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
    source_state: Mapping[str, object] | None = state if isinstance(state, Mapping) else None
    if source_state is None and isinstance(player, Mapping):
        source_state = player
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

    year, pos_x, pos_y = pstate.canonical_player_pos(source_state or {})

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

    def _line(label: str, value: str) -> str:
        return st.colorize_text(label, group=UG.DIR_OPEN) + st.colorize_text(value, group=UG.FEEDBACK_INFO)

    bus.push("SYSTEM/OK", _line("Name: ", f"{name} / Mutant {cls}"))
    bus.push("SYSTEM/OK", _line("Exhaustion : ", f"{exhaustion}"))

    bus.push("SYSTEM/OK", _line("Str: ", f"{STR:>3}") + "    " + _line("Int: ", f"{INT:>3}") + "   " + _line("Wis: ", f"{WIS:>3}"))
    bus.push("SYSTEM/OK", _line("Dex: ", f"{DEX:>3}") + "    " + _line("Con: ", f"{CON:>3}") + "   " + _line("Cha: ", f"{CHA:>3}"))

    bus.push("SYSTEM/OK", _line("Hit Points  : ", f"{hp_cur} / {hp_max}"))
    bus.push("SYSTEM/OK", _line("Exp. Points : ", f"{exp_pts:<6}") + " " + _line("Level: ", f"{level}"))
    bus.push("SYSTEM/OK", _line("Riblets     : ", f"{riblets}"))
    bus.push("SYSTEM/OK", _line("Ions        : ", f"{ions}"))
    armour_class = armour_class_for_active(state)
    dex_bonus = dex_bonus_for_active(state)
    armour_bonus = armour_class_from_equipped(state)
    bus.push(
        "SYSTEM/OK",
        _line("Wearing Armor : ", f"{armour_status}  ")
        + _line("Armour Class: ", f"{armour_class}  ")
        + _line("(Dex bonus: +", f"{dex_bonus}, Armour: +{armour_bonus})"),
    )
    ready_target_label = "NO ONE"
    ready_target_id = pstate.get_ready_target_for_active(state)
    if ready_target_id:
        ready_target_label = str(ready_target_id)
        monsters_state = ctx.get("monsters")
        target_record: Mapping[str, object] | None = None
        if monsters_state and hasattr(monsters_state, "get"):
            try:
                target_record = monsters_state.get(ready_target_id)  # type: ignore[attr-defined]
            except Exception:
                target_record = None
        if target_record:
            hp_block = target_record.get("hp")
            is_alive = True
            if isinstance(hp_block, Mapping):
                try:
                    is_alive = int(hp_block.get("current", 0)) > 0
                except (TypeError, ValueError):
                    is_alive = True
            if is_alive:
                ready_target_label = str(
                    target_record.get("name")
                    or target_record.get("monster_id")
                    or ready_target_id
                )
            else:
                pstate.clear_ready_target_for_active(reason="stats-target-dead")
                pstate.clear_ready_target_for(
                    ready_target_id, reason="stats-target-dead"
                )
                if isinstance(state, dict):
                    for key in (
                        "ready_target_by_class",
                        "target_monster_id_by_class",
                    ):
                        mapping = state.get(key)
                        if isinstance(mapping, dict):
                            for map_key in list(mapping.keys()):
                                mapping[map_key] = None
                    for scalar_key in ("ready_target", "target_monster_id"):
                        state[scalar_key] = None
                    active_block = state.get("active")
                    if isinstance(active_block, dict):
                        for field in ("ready_target", "target_monster_id"):
                            active_block[field] = None
                    players_block = state.get("players")
                    if isinstance(players_block, list):
                        for player_entry in players_block:
                            if not isinstance(player_entry, dict):
                                continue
                            for field in ("ready_target", "target_monster_id"):
                                player_entry[field] = None
                            for map_key in (
                                "ready_target_by_class",
                                "target_monster_id_by_class",
                            ):
                                player_map = player_entry.get(map_key)
                                if isinstance(player_map, dict):
                                    for class_key in list(player_map.keys()):
                                        player_map[class_key] = None
                    pstate.save_state(state)
                    ctx_state = ctx.get("player_state")
                    if isinstance(ctx_state, dict):
                        ctx["player_state"] = pstate.load_state()
                ready_target_label = "NO ONE"
                ready_target_id = None
    bus.push("SYSTEM/OK", _line("Ready to Combat: ", f"{ready_target_label}"))
    bus.push("SYSTEM/OK", _line("Readied Spell  : ", "No spell memorized."))
    bus.push("SYSTEM/OK", _line("Year A.D. : ", f"{year}"))
    bus.push("SYSTEM/OK", "")

    inv_cmd_mod.inv_cmd("", ctx)


def register(dispatch, ctx) -> None:
    dispatch.register("statistics", lambda arg: statistics_cmd(arg, ctx))
    for alias in ["sta", "stat", "stati", "statis", "statist", "statisti", "statistic"]:
        dispatch.alias(alias, "statistics")
