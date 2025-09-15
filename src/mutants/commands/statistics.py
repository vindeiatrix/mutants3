"""Statistics command for inspecting the active player."""
from __future__ import annotations

from typing import Iterable


def _pos_tuple(pos: Iterable[int]) -> tuple[int, int, int]:
    data = list(pos)
    data += [0] * max(0, 3 - len(data))
    try:
        year = int(data[0])
    except (TypeError, ValueError):
        year = 0
    try:
        x = int(data[1])
    except (TypeError, ValueError):
        x = 0
    try:
        y = int(data[2])
    except (TypeError, ValueError):
        y = 0
    return year, x, y


def statistics_cmd(arg: str, ctx) -> None:
    state_mgr = ctx.get("state_manager")
    if state_mgr is None:
        ctx["feedback_bus"].push("SYSTEM/WARN", "Statistics unavailable: state manager not initialized.")
        return
    player = state_mgr.get_active().to_dict()
    bus = ctx["feedback_bus"]

    name = player.get("name") or player.get("class") or "Unknown"
    cls = player.get("class") or player.get("class_name") or ""
    title = f"{name}"
    if cls and cls.lower() not in name.lower():
        title = f"{name} the {cls}"
    bus.push("SYSTEM/OK", title)

    level = player.get("level") or player.get("level_start") or 1
    try:
        level_val = int(level)
    except (TypeError, ValueError):
        level_val = 1
    exp_val = player.get("exp_points", player.get("exp", 0))
    bus.push("SYSTEM/OK", f"Level: {level_val}    EXP: {exp_val}")

    hp = player.get("hp", {}) if isinstance(player.get("hp"), dict) else {}
    hp_cur = hp.get("current", 0)
    hp_max = hp.get("max", 0)
    armour = player.get("armour", {}) if isinstance(player.get("armour"), dict) else {}
    ac_val = armour.get("armour_class", player.get("ac", 0))
    bus.push("SYSTEM/OK", f"HP: {hp_cur}/{hp_max}    AC: {ac_val}")

    ions = player.get("ions", 0)
    riblets = player.get("riblets", 0)
    bus.push("SYSTEM/OK", f"Money: {ions} Ions, {riblets} Riblets")

    stats = player.get("stats", {})
    if isinstance(stats, dict):
        order = ["str", "int", "wis", "dex", "con", "cha"]
        parts = []
        for key in order:
            val = stats.get(key, "?")
            parts.append(f"{key.upper()} {val}")
        bus.push("SYSTEM/OK", "Stats: " + ", ".join(parts))

    conds = player.get("conditions", {})
    active = []
    if isinstance(conds, dict):
        for name, flag in conds.items():
            if flag:
                active.append(name.replace("_", " "))
    cond_line = "none" if not active else ", ".join(active)
    bus.push("SYSTEM/OK", f"Conditions: {cond_line}")

    year, x, y = _pos_tuple(player.get("pos", [0, 0, 0]))
    bus.push("SYSTEM/OK", f"Location: Year {year}, ({x}, {y})")


def register(dispatch, ctx) -> None:
    dispatch.register("statistics", lambda arg: statistics_cmd(arg, ctx))
