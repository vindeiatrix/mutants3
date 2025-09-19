from __future__ import annotations

from typing import Dict, Mapping

from mutants.services import player_state as pstate

from . import inv as inv_cmd_mod


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def statistics_cmd(arg: str, ctx) -> None:
    # Get both the full state and the active player snapshot so we can read
    # per-class currency maps (authoritative) in addition to legacy fields.
    state, active = pstate.get_active_pair()
    player: Dict[str, object] = active if isinstance(active, dict) else {}
    state_map: Mapping[str, object] = state if isinstance(state, Mapping) else {}
    bus = ctx["feedback_bus"]

    name = player.get("name", "Unknown")
    cls = player.get("class", "Unknown")
    stats = player.get("stats")
    stats_map: Mapping[str, object] = stats if isinstance(stats, Mapping) else {}
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

    exhaustion = _int(player.get("exhaustion"))
    hp = player.get("hp")
    hp_map: Mapping[str, object] = hp if isinstance(hp, Mapping) else {}
    hp_cur = _int(hp_map.get("current"))
    hp_max = _int(hp_map.get("max"))
    exp_pts = _int(player.get("exp_points"))
    # Prefer authoritative per-class maps; fall back to legacy per-player fields.
    cls_name = str(player.get("class", "Unknown"))
    ions_map: Mapping[str, object] = state_map.get("ions_by_class", {}) if isinstance(state_map.get("ions_by_class"), Mapping) else {}
    riblets_map: Mapping[str, object] = state_map.get("riblets_by_class", {}) if isinstance(state_map.get("riblets_by_class"), Mapping) else {}
    ions = _int(ions_map.get(cls_name, player.get("ions")))
    riblets = _int(riblets_map.get(cls_name, player.get("riblets")))
    level = _int(player.get("level"), default=1)

    armour = player.get("armour")
    if isinstance(armour, Mapping):
        wearing = armour.get("wearing")
        ac = _int(armour.get("armour_class"))
    else:
        wearing = None
        ac = 0

    bus.push("SYSTEM/OK", f"Name: {name} / Mutant {cls}")
    bus.push("SYSTEM/OK", f"Exhaustion : {exhaustion}")

    bus.push("SYSTEM/OK", f"Str: {STR:>3}    Int: {INT:>3}   Wis: {WIS:>3}")
    bus.push("SYSTEM/OK", f"Dex: {DEX:>3}    Con: {CON:>3}   Cha: {CHA:>3}")

    bus.push("SYSTEM/OK", f"Hit Points  : {hp_cur} / {hp_max}")
    bus.push("SYSTEM/OK", f"Exp. Points : {exp_pts:<6} Level: {level}")
    bus.push("SYSTEM/OK", f"Riblets     : {riblets}")
    bus.push("SYSTEM/OK", f"Ions        : {ions}")
    armour_status = "None" if wearing is None else wearing
    bus.push("SYSTEM/OK", f"Wearing Armor : {armour_status}  Armour Class: {ac}")
    bus.push("SYSTEM/OK", "Ready to Combat: NO ONE")
    bus.push("SYSTEM/OK", "Readied Spell  : No spell memorized.")
    bus.push("SYSTEM/OK", f"Year A.D. : {year}")
    bus.push("SYSTEM/OK", "")

    inv_cmd_mod.inv_cmd("", ctx)


def register(dispatch, ctx) -> None:
    dispatch.register("statistics", lambda arg: statistics_cmd(arg, ctx))
    for alias in ["sta", "stat", "stati", "statis", "statist", "statisti", "statistic"]:
        dispatch.alias(alias, "statistics")
