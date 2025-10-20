from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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


def _monster_id(monster: Mapping[str, Any]) -> str:
    raw_id = monster.get("id") or monster.get("instance_id") or monster.get("monster_id")
    return str(raw_id) if raw_id else ""


def _monster_display_name(monster: Mapping[str, Any]) -> str:
    name = monster.get("display_name") or monster.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    ident = _monster_id(monster)
    return ident or "monster"


def _monster_base_name(monster: Mapping[str, Any]) -> str:
    base = monster.get("base_name")
    if isinstance(base, str) and base.strip():
        return base.strip()
    display = _monster_display_name(monster)
    suffix = monster.get("instance_suffix")
    if isinstance(suffix, int) and suffix >= 0:
        token = f"-{suffix}"
        if display.endswith(token):
            return display[: -len(token)]
    return display


def _monster_suffix(monster: Mapping[str, Any]) -> Optional[int]:
    suffix = monster.get("instance_suffix")
    if isinstance(suffix, int) and suffix >= 0:
        return suffix
    if isinstance(suffix, str) and suffix.isdigit():
        return int(suffix)
    display = _monster_display_name(monster)
    parts = display.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def _format_example_target(base_name: str, suffix: Optional[int]) -> str:
    name = base_name.strip() if base_name else "Monster"
    if suffix is None:
        return name
    return f"{name}-{suffix}"


def _find_target_monster(
    token: str,
    monsters: Sequence[Mapping[str, Any]],
    bus: Any,
) -> Tuple[Optional[Mapping[str, Any]], Optional[str], Optional[str], str]:
    normalized = normalize_item_query(token)
    lowered = token.strip().lower()

    def _matches_display(monster: Mapping[str, Any]) -> bool:
        display = _monster_display_name(monster)
        return bool(normalized and normalize_item_query(display) == normalized)

    display_matches = [mon for mon in monsters if _matches_display(mon)]
    if len(display_matches) == 1:
        target = display_matches[0]
        ident = _monster_id(target)
        return target, ident, _monster_display_name(target), "ok"
    if len(display_matches) > 1:
        base_name = _monster_base_name(display_matches[0])
        suffix = _monster_suffix(display_matches[0])
        example = _format_example_target(base_name, suffix)
        bus.push(
            "SYSTEM/WARN",
            f"Multiple {base_name} monsters found. Specify by number (e.g., com {example}).",
        )
        return None, None, None, "ambiguous"

    for monster in monsters:
        monster_id = _monster_id(monster)
        if monster_id and monster_id.lower() == lowered:
            return monster, monster_id, _monster_display_name(monster), "ok"
        if normalized and monster_id and normalize_item_query(monster_id) == normalized:
            return monster, monster_id, _monster_display_name(monster), "ok"

    base_matches: List[Mapping[str, Any]] = []
    for monster in monsters:
        base_name = _monster_base_name(monster)
        if normalized and normalize_item_query(base_name).startswith(normalized):
            base_matches.append(monster)

    if len(base_matches) == 1:
        target = base_matches[0]
        ident = _monster_id(target)
        return target, ident, _monster_display_name(target), "ok"

    if len(base_matches) > 1:
        base_name = _monster_base_name(base_matches[0])
        suffix = _monster_suffix(base_matches[0])
        example = _format_example_target(base_name, suffix)
        bus.push(
            "SYSTEM/WARN",
            f"Multiple {base_name} monsters found. Specify by number (e.g., com {example}).",
        )
        return None, None, None, "ambiguous"

    bus.push("SYSTEM/WARN", f"No monster here matches '{token}'.")
    return None, None, None, "not_found"


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

    target_monster, target_id, target_name, status = _find_target_monster(token, living, bus)
    if status != "ok" or not target_monster or not target_id:
        return {"ok": False, "reason": status}

    sanitized = pstate.set_ready_target_for_active(target_id)
    pstate.set_runtime_combat_target(ctx.get("player_state"), (sanitized or target_id) or None)
    label = target_name if target_name else (sanitized or target_id)
    bus.push("SYSTEM/OK", f"You ready yourself against {label}.")
    return {"ok": True, "target_id": sanitized or target_id, "target_name": label}


def register(dispatch, ctx) -> None:
    dispatch.register("combat", lambda arg: combat_cmd(arg, ctx))
    dispatch.alias("com", "combat")
