from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from mutants.services import player_state as pstate
from mutants.util.textnorm import normalize_item_query

CLEAR_TOKENS = {"none", "clear", "cancel"}


def _coerce_position(player: Mapping[str, Any]) -> Optional[Tuple[int, int, int]]:
    pos = player.get("pos")
    if isinstance(pos, (list, tuple)) and len(pos) >= 3:
        try:
            return int(pos[0]), int(pos[1]), int(pos[2])
        except (TypeError, ValueError):
            return None
    return None


def _list_monsters(
    monsters: Any, year: int, x: int, y: int
) -> List[Mapping[str, Any]]:
    if not monsters or not hasattr(monsters, "list_at"):
        return []
    try:
        return [mon for mon in monsters.list_at(year, x, y)]  # type: ignore[attr-defined]
    except Exception:
        return []


def _is_alive(monster: Mapping[str, Any]) -> bool:
    hp_block = monster.get("hp")
    if isinstance(hp_block, Mapping):
        try:
            return int(hp_block.get("current", 0)) > 0
        except (TypeError, ValueError):
            return True
    return True


def _display_name(monster: Mapping[str, Any], fallback_id: str) -> str:
    name = monster.get("name") or monster.get("monster_id")
    return str(name) if name else fallback_id


def combat_cmd(arg: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    bus = ctx["feedback_bus"]
    token = (arg or "").strip()
    if not token:
        bus.push("SYSTEM/WARN", "Usage: combat <monster>")
        return {"ok": False, "reason": "missing_argument"}

    lowered = token.lower()
    if lowered in CLEAR_TOKENS:
        previous = pstate.clear_ready_target_for_active(reason="user-clear")
        pstate.set_runtime_combat_target(ctx.get("player_state"), None)
        message = "You lower your guard." if previous else "You are not ready to fight anyone."
        bus.push("SYSTEM/OK", message)
        return {"ok": True, "cleared": True}

    normalized = normalize_item_query(token)
    state, active = pstate.get_active_pair()
    player: Mapping[str, Any] = active if isinstance(active, Mapping) else {}
    pos = _coerce_position(player)
    if not pos:
        bus.push("SYSTEM/WARN", "You are nowhere to engage in combat.")
        pstate.clear_ready_target_for_active(reason="invalid-position")
        pstate.set_runtime_combat_target(ctx.get("player_state"), None)
        return {"ok": False, "reason": "invalid_position"}

    year, px, py = pos
    monsters_state = ctx.get("monsters")
    monsters_here = _list_monsters(monsters_state, year, px, py)
    living = [mon for mon in monsters_here if _is_alive(mon)]
    if not living:
        pstate.clear_ready_target_for_active(reason="no-monsters")
        pstate.set_runtime_combat_target(ctx.get("player_state"), None)
        bus.push("SYSTEM/WARN", "No living monsters here to fight.")
        return {"ok": False, "reason": "no_monsters"}

    matches: List[Tuple[int, int, Mapping[str, Any], str]] = []
    norm_token = normalized or lowered
    for index, monster in enumerate(living):
        raw_id = monster.get("id") or monster.get("instance_id") or monster.get("monster_id")
        monster_id = str(raw_id) if raw_id else ""
        norm_id = normalize_item_query(monster_id)
        display_name = _display_name(monster, monster_id or "monster")
        norm_name = normalize_item_query(display_name)
        if not norm_token:
            continue
        if norm_id.startswith(norm_token):
            priority = 0 if norm_id == norm_token else 1
        elif monster_id and monster_id.lower().startswith(lowered):
            priority = 0 if monster_id.lower() == lowered else 2
        elif norm_name.startswith(norm_token):
            priority = 0 if norm_name == norm_token else 3
        else:
            continue
        matches.append((priority, index, monster, monster_id))

    if not matches:
        bus.push("SYSTEM/WARN", f"No monster here matches '{token}'.")
        return {"ok": False, "reason": "not_found"}

    matches.sort(key=lambda entry: (entry[0], entry[1]))
    _, _, target_monster, target_id = matches[0]
    sanitized = pstate.set_ready_target_for_active(target_id)
    pstate.set_runtime_combat_target(ctx.get("player_state"), (sanitized or target_id) or None)
    label = _display_name(target_monster, sanitized or target_id)
    bus.push("SYSTEM/OK", f"You ready yourself against {label}.")
    return {"ok": True, "target_id": sanitized or target_id, "target_name": label}


def register(dispatch, ctx) -> None:
    dispatch.register("combat", lambda arg: combat_cmd(arg, ctx))
    dispatch.alias("com", "combat")
