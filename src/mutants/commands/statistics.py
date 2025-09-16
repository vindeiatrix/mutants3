"""Statistics command for inspecting the active player."""
from __future__ import annotations


def _col(label: str, value: str, width: int = 16) -> str:
    return f"{label:<{width}} : {value}"


def _name_line(player: dict) -> str:
    name_raw = player.get("name") or player.get("class") or "Unknown"
    cls_raw = player.get("class") or player.get("class_name") or ""
    name = str(name_raw).strip()
    cls = str(cls_raw).strip()
    if cls and cls.lower() not in name.lower():
        disp = f"{name} / Mutant {cls}"
    else:
        disp = f"{name} / Mutant {cls or name}"
    return f"Name: {disp}"


def _num(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _hp(player: dict) -> tuple[int, int]:
    hp = player.get("hp") or {}
    if isinstance(hp, dict):
        current = _num(hp.get("current"))
        maximum = _num(hp.get("max"))
    else:
        current = maximum = _num(hp)
    return current, maximum


def _ac(player: dict) -> int:
    armour = player.get("armour") or {}
    if isinstance(armour, dict):
        value = armour.get("armour_class", player.get("ac", 1))
    else:
        value = armour or player.get("ac", 1)
    return _num(value, 1)


def _year(player: dict) -> int:
    pos = player.get("pos") or [2000, 0, 0]
    if isinstance(pos, (list, tuple)) and pos:
        return _num(pos[0], 2000)
    return 2000


def _item_display(items, iid) -> str:
    for attr in ("get_display_name", "display_name", "name_of", "describe"):
        fn = getattr(items, attr, None)
        if callable(fn):
            try:
                info = fn(iid)
                if isinstance(info, dict):
                    return str(info.get("name") or iid)
                return str(info)
            except Exception:
                pass
    return str(iid)


def _item_weight_lb(items, iid) -> int:
    for attr in ("weight_lb", "get_weight_lb", "describe"):
        fn = getattr(items, attr, None)
        if callable(fn):
            try:
                info = fn(iid)
                if isinstance(info, dict):
                    return _num(info.get("weight_lb"), 0)
                return _num(info, 0)
            except Exception:
                pass
    return 0


def _armour_name(player: dict) -> str:
    armour = player.get("armour") or {}
    if isinstance(armour, dict):
        for key in ("display_name", "name", "id"):
            value = armour.get(key)
            if value:
                return str(value)
    elif armour:
        return str(armour)
    return "Nothing."


def _player_dict(ctx) -> dict:
    state_mgr = ctx.get("state_manager")
    if state_mgr is None:
        return {}
    try:
        active = state_mgr.get_active()
    except Exception:
        return {}
    if active is None:
        return {}
    if hasattr(active, "to_dict"):
        try:
            data = active.to_dict() or {}
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    if isinstance(active, dict):
        return active
    return {}


def statistics_cmd(arg: str, ctx) -> None:
    bus = ctx.get("feedback_bus")
    if bus is None:
        return

    player = _player_dict(ctx)

    stats = player.get("stats") or {}
    if not isinstance(stats, dict):
        stats = {}
    stats_values = {key: _num(stats.get(key)) for key in ("str", "int", "wis", "dex", "con", "cha")}

    hp_current, hp_max = _hp(player)
    level = _num(player.get("level", player.get("level_start")), 1)
    exhaustion = _num(player.get("exhaustion"))
    exp_points = _num(player.get("exp_points", player.get("exp")))
    riblets = _num(player.get("riblets"))
    ions = _num(player.get("ions"))
    armour_class = _ac(player)
    armour_name = _armour_name(player)
    year = _year(player)

    lines = [
        _name_line(player),
        _col("Exhaustion", str(exhaustion)),
        f"Str: {stats_values['str']:<2}     Int: {stats_values['int']:<2}     Wis: {stats_values['wis']:<2}",
        f"Dex: {stats_values['dex']:<2}     Con: {stats_values['con']:<2}    Cha: {stats_values['cha']:<2}",
        f"{_col('Hit Points', f'{hp_current} / {hp_max}')}      Level: {level}",
        _col("Exp. Points", str(exp_points)),
        _col("Riblets", str(riblets)),
        _col("Ions", str(ions)),
        f"{_col('Wearing Armor', armour_name)}   Armour Class: {armour_class}",
        _col("Ready to Combat", "NO ONE"),
        _col("Readied Spell", "No spell memorized."),
        _col("Year A.D.", str(year)),
        "",
    ]

    inventory = player.get("inventory") or []
    if not isinstance(inventory, (list, tuple)):
        inventory = [inventory] if inventory else []

    items_registry = ctx.get("items")
    inventory_lines = []
    total_weight = 0

    for entry in inventory:
        item_dict = entry if isinstance(entry, dict) else None
        iid = None
        if isinstance(entry, dict):
            iid = entry.get("id") or entry.get("name")
        else:
            iid = entry

        display_name = None
        if items_registry is not None and iid is not None:
            try:
                display_name = _item_display(items_registry, iid)
            except Exception:
                display_name = None
        if display_name is None and item_dict:
            display_name = item_dict.get("name") or item_dict.get("display_name")
        if display_name is None:
            display_name = str(iid)

        weight = 0
        if items_registry is not None and iid is not None:
            try:
                weight = _item_weight_lb(items_registry, iid)
            except Exception:
                weight = 0
        if weight == 0 and item_dict:
            candidate = item_dict.get("weight_lb") or item_dict.get("weight")
            if candidate is not None:
                weight = _num(candidate, 0)
        try:
            total_weight += int(weight)
        except Exception:
            pass

        inventory_lines.append(str(display_name))

    lines.append(f"You are carrying the following items:  (Total Weight: {total_weight} LB's)")
    if inventory_lines:
        lines.extend(inventory_lines)
    else:
        lines.append("Nothing.")

    for line in lines:
        bus.push("SYSTEM/OK", line)


def register(dispatch, ctx) -> None:
    dispatch.register("statistics", lambda arg: statistics_cmd(arg, ctx))
