from __future__ import annotations

from typing import Dict
import os
from collections.abc import Mapping

from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate
from mutants.services.combat_calc import (
    armour_class_for_active,
    armour_class_from_equipped,
    dex_bonus_for_active,
)
from mutants.services.items_weight import get_effective_weight
from mutants.ui import styles as st
from mutants.ui import groups as UG
from mutants.ui.item_display import item_label, number_duplicates, with_article
from mutants.ui import wrap as uwrap
from mutants.ui.textutils import harden_final_display

from . import inv as inv_cmd_mod


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _coerce_weight(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def statistics_cmd(arg: str, ctx) -> None:
    prev_ansi = getattr(st, "_ANSI_ENABLED", True)
    if os.getenv("PYTEST_CURRENT_TEST"):
        st.set_ansi_enabled(False)
    state_hint = ctx.get("player_state") if isinstance(ctx, Mapping) else None
    if isinstance(state_hint, Mapping):
        pstate.normalize_player_state_inplace(state_hint)
    state, active = pstate.get_active_pair(state_hint)
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

    # Align colons vertically across the single-column rows.
    LABEL_COL = 14

    def _pad_label(text: str) -> str:
        return f"{text:<{LABEL_COL}}: "

    def _attr(label: str, value: int | str) -> str:
        # Single space between the label and value; pad value to keep columns tidy without leading blanks.
        return _line(f"{label}: ", f"{value:<3}")

    NAME_LABEL = "Name: "
    lines = [
        _line(NAME_LABEL, f"{name} / Mutant {cls}"),
        _line(_pad_label("Exhaustion"), f"{exhaustion}"),
        _attr("Str", STR) + "    " + _attr("Int", INT) + "     " + _attr("Wis", WIS),
        _attr("Dex", DEX) + "    " + _attr("Con", CON) + "     " + _attr("Cha", CHA),
        _line(_pad_label("Hit Points"), f"{hp_cur} / {hp_max}"),
        _line(_pad_label("Exp. Points"), f"{exp_pts}") + "  " + _line("Level: ", f"{level}"),
        _line(_pad_label("Riblets"), f"{riblets}"),
        _line(_pad_label("Ions"), f"{ions}"),
    ]
    armour_class = armour_class_for_active(state)
    dex_bonus = dex_bonus_for_active(state)
    armour_bonus = armour_class_from_equipped(state)
    lines.append(
        _line(_pad_label("Wearing Armor"), f"{armour_status}  ")
        + _line("Armour Class: ", f"{armour_class}")
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
    lines.append(_line(_pad_label("Ready to Combat"), f"{ready_target_label}"))
    lines.append(_line("Readied Spell  : ", "No spell memorized."))
    lines.append(_line("Year A.D.      : ", f"{year}"))

    # Inline inventory block into the same event to avoid separator lines between stats and bag.
    inv_state, inv_player = pstate.get_active_pair(state_hint)
    pstate.bind_inventory_to_active_class(inv_player)
    inventory = [str(i) for i in (inv_player.get("inventory") or []) if i]
    equipped = pstate.get_equipped_armour_id(inv_state) or pstate.get_equipped_armour_id(inv_player)
    if equipped:
        inventory = [iid for iid in inventory if iid != equipped]
    cat = items_catalog.load_catalog()
    names = []
    total_weight = 0
    for iid in inventory:
        inst = itemsreg.get_instance(iid)
        if not inst:
            names.append(str(iid))
            continue
        tpl_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
        tpl = cat.get(str(tpl_id)) if tpl_id and cat else {}
        names.append(item_label(inst, tpl or {}, show_charges=False))
        weight = _coerce_weight(get_effective_weight(inst, tpl or {}))
        if weight is not None:
            total_weight += max(0, weight)

    numbered = number_duplicates(names)
    display = [harden_final_display(with_article(n)) for n in numbered]
    inv_lines = [
        st.colorize_text(
            f"You are carrying the following items:  (Total Weight: {total_weight} LB's)",
            group=UG.HEADER,
        )
    ]
    if not display:
        inv_lines.append("Nothing.")
    else:
        inv_lines.extend([st.colorize_text(ln, group=UG.LOG_LINE) for ln in uwrap.wrap_list(display)])
    combined = lines + [""] + inv_lines
    bus.push("SYSTEM/OK", "\n".join(combined))
    st.set_ansi_enabled(prev_ansi)


def register(dispatch, ctx) -> None:
    dispatch.register("statistics", lambda arg: statistics_cmd(arg, ctx))
    for alias in ["sta", "stat", "stati", "statis", "statist", "statisti", "statistic"]:
        dispatch.alias(alias, "statistics")
