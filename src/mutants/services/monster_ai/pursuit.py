"""Pursuit helpers for monster AI movement."""

from __future__ import annotations

import logging
import random
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from mutants.debug import turnlog
from mutants.engine import edge_resolver
from mutants.registries import dynamics as dynamics_registry
from mutants.registries import items_instances as itemsreg
from mutants.registries import world as world_registry
from mutants.services import audio_cues, combat_loot
from mutants.services import monsters_state
from mutants.services.combat_config import CombatConfig
from mutants.world import years as world_years

LOG = logging.getLogger(__name__)

_BASE_CHANCE = 85
_HP_DISTRACTION_THRESHOLD = 40
_LOOT_DISTRACTION_PENALTY = 10
_ION_DISTRACTION_PENALTY = 5
_HP_DISTRACTION_PENALTY = 10
_CRACKED_DISTRACTION_PENALTY = 10

_DIRECTIONS = {
    (1, 0): "E",
    (-1, 0): "W",
    (0, 1): "N",
    (0, -1): "S",
}


def _monster_id(monster: Mapping[str, Any]) -> str:
    for key in ("id", "instance_id", "monster_id"):
        raw = monster.get(key)
        if raw is None:
            continue
        token = str(raw).strip()
        if token:
            return token
    return "?"


def _monster_display_name(monster: Mapping[str, Any]) -> str:
    name = monster.get("name") or monster.get("monster_id")
    if isinstance(name, str) and name.strip():
        return name
    return _monster_id(monster)


def _bag_entries(monster: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bag = monster.get("bag")
    if isinstance(bag, Sequence) and not isinstance(bag, (str, bytes)):
        entries: list[Mapping[str, Any]] = []
        for entry in bag:
            if isinstance(entry, Mapping):
                entries.append(entry)
        return entries
    return []


def _is_cracked_entry(entry: Mapping[str, Any]) -> bool:
    item_id = str(entry.get("item_id") or entry.get("catalog_id") or "").strip()
    if not item_id:
        return False
    if item_id != itemsreg.BROKEN_WEAPON_ID:
        return False
    enchant = entry.get("enchant_level")
    try:
        enchant_val = int(enchant)
    except (TypeError, ValueError):
        enchant_val = 0
    return enchant_val <= 0


def _is_wielded_cracked(monster: Mapping[str, Any], bag: Sequence[Mapping[str, Any]]) -> bool:
    wielded = monster.get("wielded")
    if wielded is None:
        return False
    token = str(wielded)
    if not token:
        return False
    for entry in bag:
        iid = entry.get("iid")
        if iid is None:
            continue
        if str(iid) != token:
            continue
        return _is_cracked_entry(entry)
    return False


def _ground_items(monster: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pos = combat_loot.coerce_pos(monster.get("pos"))
    if pos is None:
        return []
    year, x, y = pos
    list_at = getattr(itemsreg, "list_instances_at", None)
    if not callable(list_at):
        return []
    try:
        items = list_at(year, x, y)
    except Exception:  # pragma: no cover - defensive
        return []
    result: list[Mapping[str, Any]] = []
    if isinstance(items, Iterable):
        for entry in items:
            if isinstance(entry, Mapping):
                result.append(entry)
    return result


def _has_pickup_candidate(monster: Mapping[str, Any]) -> bool:
    for entry in _ground_items(monster):
        item_id = str(entry.get("item_id") or entry.get("catalog_id") or "").strip()
        if not item_id:
            continue
        if item_id in {itemsreg.BROKEN_WEAPON_ID, itemsreg.BROKEN_ARMOUR_ID}:
            continue
        return True
    return False


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hp_pct(monster: Mapping[str, Any]) -> int:
    hp_block = monster.get("hp")
    if isinstance(hp_block, Mapping):
        current = _coerce_int(hp_block.get("current"), 0)
        maximum = _coerce_int(hp_block.get("max"), max(current, 1))
    else:
        current = _coerce_int(monster.get("hp_current"), 0)
        maximum = _coerce_int(monster.get("hp_max"), max(current, 1))
    maximum = max(1, maximum)
    pct = int(round((max(0, current) / maximum) * 100))
    return max(0, min(100, pct))


def _ions(monster: Mapping[str, Any]) -> tuple[int, int]:
    ions = _coerce_int(monster.get("ions"), 0)
    ions_max = monster.get("ions_max")
    if ions_max is None:
        ions_max = monster.get("ionsMaximum")
    ions_max = _coerce_int(ions_max, 0)
    return max(0, ions), max(0, ions_max)


def _ions_pct(ions: int, ions_max: int) -> int:
    if ions_max <= 0:
        return 100
    pct = int(round((max(0, ions) / ions_max) * 100))
    return max(0, min(100, pct))


def _clamp_pct(value: int) -> int:
    return max(0, min(100, value))


def _resolve_world_loader(ctx: Any) -> Any:
    candidate = None
    if isinstance(ctx, Mapping):
        candidate = ctx.get("monster_ai_world_loader")
    else:
        candidate = getattr(ctx, "monster_ai_world_loader", None)
    if callable(candidate):
        return candidate
    return world_registry.load_year


def _resolve_dynamics(ctx: Any) -> Any:
    if isinstance(ctx, Mapping):
        candidate = ctx.get("monster_ai_dynamics")
    else:
        candidate = getattr(ctx, "monster_ai_dynamics", None)
    return candidate if candidate is not None else dynamics_registry


def _log(ctx: Any, monster: Mapping[str, Any], *, success: bool, reason: str, **meta: Any) -> None:
    payload = {"monster": _monster_id(monster), "success": success, "reason": reason}
    payload.update(meta)
    turnlog.emit(ctx, "AI/PURSUIT", **payload)
    if success:
        LOG.info("AI/PURSUIT success=%s reason=%s meta=%s", success, reason, {k: meta[k] for k in sorted(meta)})
    else:
        LOG.debug("AI/PURSUIT success=%s reason=%s meta=%s", success, reason, {k: meta[k] for k in sorted(meta)})


def _emit_arrival_and_noise(
    ctx: Any,
    monster_pos: Iterable[int] | None,
    player_pos: Iterable[int] | None,
    *,
    movement: tuple[int, int] | None,
    flee_mode: bool,
    has_bound_target: bool = False,
    rng: Any | None = None,
    arrived_dir: str | None = None,
    allow_shadow: bool = True,
    force_direction: str | None = None,
) -> None:
    """Emit arrival/noise cues tuned for flee mode."""

    mon = combat_loot.coerce_pos(monster_pos)
    ply = combat_loot.coerce_pos(player_pos)
    if mon is None or ply is None or len(mon) != 3 or len(ply) != 3:
        return
    my, mx, myy = mon  # keep tuple unpack simple
    py, px, pyy = ply
    if int(my) != int(py):
        return
    dx = int(mx) - int(px)
    dy = int(myy) - int(pyy)
    # If co-located after movement, use the previous step direction for audio cues,
    # and capture a shadow hint/arrival direction.
    audio_mon_pos = mon
    arrived_dir_token = None
    is_arrival_step = dx == 0 and dy == 0 and movement
    if is_arrival_step:
        try:
            prev_x = int(mx) - int(movement[0])
            prev_y = int(myy) - int(movement[1])
            audio_mon_pos = (int(my), prev_x, prev_y)
            dx = prev_x - int(px)
            dy = prev_y - int(pyy)
            mdx, mdy = movement
            if abs(mdx) >= abs(mdy):
                arrived_dir_token = "west" if mdx > 0 else "east"
            else:
                arrived_dir_token = "south" if mdy > 0 else "north"
        except Exception:
            pass

    direction = None
    if abs(dx) + abs(dy) == 1:
        if dx == 1:
            direction = "east"
        elif dx == -1:
            direction = "west"
        elif dy == 1:
            direction = "north"
        elif dy == -1:
            direction = "south"
    bus = ctx.get("feedback_bus") if isinstance(ctx, Mapping) else getattr(ctx, "feedback_bus", None)
    if not hasattr(bus, "push"):
        return
    try:
        # Optional yelling/screaming roll when bound and not co-located.
        dist = max(abs(dx), abs(dy))
        if has_bound_target and dist > 0:
            try:
                roll = int(rng.randrange(100)) if rng is not None else None
            except Exception:
                roll = None
            if roll is None:
                import random as _rand

                roll = int(_rand.Random().randrange(100))
            if roll < 60:  # ~60% chance per frame to better match reference frequency
                scream = audio_cues.emit_sound(
                    audio_mon_pos,
                    player_pos,
                    kind="yelling",
                    ctx=ctx,
                    movement=movement,
                )
                if scream and isinstance(ctx, Mapping):
                    ctx["_ai_emitted_audio"] = True

        # Footsteps (audible within hearing range) for both pursue and flee, except suppress on arrival frame.
        if not is_arrival_step:
            try:
                msg = audio_cues.emit_sound(audio_mon_pos, player_pos, kind="footsteps", ctx=ctx, movement=movement)
                if msg and isinstance(ctx, Mapping):
                    ctx["_ai_emitted_audio"] = True
            except Exception:
                LOG.debug("Failed to emit movement footsteps", exc_info=True)

        if allow_shadow and isinstance(ctx, MutableMapping):
            try:
                if dist == 1:
                    ctx["_suppress_shadows_once"] = True
                if is_arrival_step:
                    shadow_dir = arrived_dir_token or direction
                    if shadow_dir:
                        ctx["_shadow_hint_once"] = [shadow_dir]
            except Exception:
                pass

        if not flee_mode:
            return

        target_dir = force_direction or arrived_dir or direction
        # For flee we already emitted footsteps/yelling above; no extra manual push needed.
    except Exception:
        LOG.debug("Failed to push flee noise cues", exc_info=True)


def _apply_movement(
    monster: MutableMapping[str, Any],
    year: int,
    start: tuple[int, int],
    target: tuple[int, int],
    ctx: Any,
    *,
    allow_path: bool = True,
) -> tuple[bool, dict[str, Any]]:
    loader = _resolve_world_loader(ctx)
    dynamics = _resolve_dynamics(ctx)
    try:
        world = loader(year)
    except Exception:
        return False, {"reason": "world-unavailable"}

    sx, sy = start
    tx, ty = target
    dx = tx - sx
    dy = ty - sy

    details: dict[str, Any] = {"from": start, "target": target}

    step_taken: tuple[int, int] | None = None

    direction = _DIRECTIONS.get((dx, dy))
    if direction is not None:
        decision = edge_resolver.resolve(
            world,
            dynamics,
            year,
            sx,
            sy,
            direction,
            actor={"kind": "monster"},
        )
        details["direct_reason"] = decision.reason
        if decision.passable:
            step_taken = (tx, ty)
            details.update({"mode": "direct", "step": step_taken, "dir": direction})
    else:
        details["mode"] = "non-adjacent"

    if step_taken is None:
        if not allow_path:
            details.setdefault("mode", "blocked")
            details.setdefault("reason", details.get("direct_reason", "blocked"))
            return False, details
        path = world_years.find_path_between(
            year,
            start,
            target,
            world=world,
            dynamics=dynamics,
        )
        if len(path) >= 2:
            step_taken = path[1]
            details.update({"mode": "path", "step": step_taken, "path_len": len(path)})
        else:
            details.setdefault("path_len", len(path))
            details.setdefault("mode", "blocked")
            details.setdefault("reason", details.get("direct_reason", "blocked"))
            return False, details

    monster["pos"] = [year, step_taken[0], step_taken[1]]
    try:
        monsters_state._refresh_monster_derived(monster)
    except Exception:
        pass
    try:
        monsters_obj = ctx.get("monsters") if isinstance(ctx, Mapping) else getattr(ctx, "monsters", None)
        updater = getattr(monsters_obj, "update_position_cache", None)
        if callable(updater):
            updater(monster, previous_pos=(year, start[0], start[1]))
    except Exception:
        pass
    return True, details


def attempt_pursuit(
    monster: MutableMapping[str, Any],
    target_pos: Iterable[int] | Mapping[str, Any],
    rng: Any,
    *,
    ctx: Any | None = None,
    config: CombatConfig | None = None,
) -> bool:
    """Attempt to move ``monster`` toward ``target_pos`` using pursuit rules."""

    pos = combat_loot.coerce_pos(monster.get("pos"))
    target = combat_loot.coerce_pos(target_pos)
    if pos is None or target is None:
        _log(ctx, monster, success=False, reason="invalid-pos", pos=pos, target=target)
        return False

    year, sx, sy = pos
    t_year, tx, ty = target
    if int(year) != int(t_year):
        _log(ctx, monster, success=False, reason="cross-year", pos=pos, target=target)
        return False

    config_obj = config if isinstance(config, CombatConfig) else CombatConfig()

    bag = _bag_entries(monster)
    modifiers: list[str] = []
    chance = _BASE_CHANCE

    if _has_pickup_candidate(monster):
        chance -= _LOOT_DISTRACTION_PENALTY
        modifiers.append("loot")

    ions, ions_max = _ions(monster)
    ions_pct = _ions_pct(ions, ions_max)
    if ions_max > 0 and ions_pct < config_obj.low_ion_pct:
        chance -= _ION_DISTRACTION_PENALTY
        modifiers.append("low_ions")

    hp_pct = _hp_pct(monster)
    if hp_pct < _HP_DISTRACTION_THRESHOLD:
        chance -= _HP_DISTRACTION_PENALTY
        modifiers.append("low_hp")

    if _is_wielded_cracked(monster, bag):
        chance -= _CRACKED_DISTRACTION_PENALTY
        modifiers.append("cracked")

    # Bound monsters (explicit target) should always choose to pursue, matching
    # the desired deterministic chase behaviour.
    state = monster.get("_ai_state") if isinstance(monster, Mapping) else None
    pending_target = None
    if isinstance(state, Mapping):
        pending_target = state.get("pending_pursuit")
    has_bound_target = bool(monster.get("target_player_id") or pending_target)
    if has_bound_target:
        roll = 0
        threshold = 100
    else:
        threshold = _clamp_pct(chance)
        try:
            roll = int(rng.randrange(100))
        except Exception:
            roll = int(random.Random().randrange(100))

    meta = {
        "threshold": threshold,
        "roll": roll,
        "modifiers": tuple(modifiers),
        "hp_pct": hp_pct,
        "ions_pct": ions_pct,
        "ions": ions,
        "ions_max": ions_max,
    }

    if not has_bound_target and roll >= threshold:
        reason = f"roll={roll} threshold={threshold}"
        _log(ctx, monster, success=False, reason=reason, **meta)
        return False

    start_pos = (int(sx), int(sy))
    target_pos = (int(tx), int(ty))
    success, details = _apply_movement(monster, int(year), start_pos, target_pos, ctx)
    if success:
        meta.update(details)
        _log(ctx, monster, success=True, reason="moved", **meta)
        try:
            monster_pos = monster.get("pos")
        except Exception:  # pragma: no cover - defensive
            monster_pos = None
        movement: tuple[int, int] | None = None
        try:
            step = details.get("step")
            if isinstance(step, Sequence) and len(step) == 2:
                mx = int(step[0]) - int(start_pos[0])
                my = int(step[1]) - int(start_pos[1])
                if mx != 0 or my != 0:
                    movement = (mx, my)
        except Exception:  # pragma: no cover - defensive guard
            movement = None
        _emit_arrival_and_noise(
            ctx,
            monster_pos,
            target,
            movement=movement,
            flee_mode=False,
            has_bound_target=has_bound_target,
            rng=rng,
        )
        # Arrival cue when entering player tile.
        player_pos = combat_loot.coerce_pos(target)
        monster_pos_norm = combat_loot.coerce_pos(monster_pos)
        if player_pos and monster_pos_norm and int(player_pos[0]) == int(monster_pos_norm[0]):
            dx = int(monster_pos_norm[1]) - int(player_pos[1])
            dy = int(monster_pos_norm[2]) - int(player_pos[2])
            if abs(dx) + abs(dy) == 0 and movement:
                dir_token = None
                mdx, mdy = movement
                if abs(mdx) >= abs(mdy):
                    dir_token = "west" if mdx > 0 else "east"  # direction monster came from
                else:
                    dir_token = "south" if mdy > 0 else "north"
                bus = ctx.get("feedback_bus") if isinstance(ctx, Mapping) else getattr(ctx, "feedback_bus", None)
                name = _monster_display_name(monster)
                if dir_token and hasattr(bus, "push"):
                    try:
                        bus.push("COMBAT/INFO", f"{name} has just arrived from the {dir_token}.")
                        # Hide the presence line until the next player action so arrival text
                        # and presence are not in the same frame.
                        try:
                            if isinstance(ctx, MutableMapping):
                                ctx["_suppress_monsters_once"] = True
                        except Exception:
                            pass
                    except Exception:
                        LOG.debug("Failed to push arrival cue", exc_info=True)
        return True

    meta.update(details)
    # Avoid passing duplicate 'reason' twice via meta
    meta.pop("reason", None)
    _log(ctx, monster, success=False, reason=details.get("reason", details.get("direct_reason", "blocked")), **meta)
    return False


def attempt_flee_step(
    monster: MutableMapping[str, Any],
    away_from_pos: Iterable[int] | Mapping[str, Any] | None,
    rng: Any,
    *,
    ctx: Any | None = None,
    preferred_direction: str | None = None,
) -> bool:
    """Try to take a single step strictly away from ``away_from_pos``."""

    pos = combat_loot.coerce_pos(monster.get("pos"))
    away = combat_loot.coerce_pos(away_from_pos) if away_from_pos is not None else None
    if pos is None or away is None:
        _log(ctx, monster, success=False, reason="invalid-pos", pos=pos, away=away)
        return False

    year, sx, sy = pos
    if int(away[0]) != int(year):
        _log(ctx, monster, success=False, reason="cross-year", pos=pos, away=away)
        return False

    current_distance = abs(int(sx) - int(away[1])) + abs(int(sy) - int(away[2]))

    preferred_step: tuple[int, int] | None = None
    if preferred_direction in ("N", "S", "E", "W"):
        pdx, pdy = 0, 0
        if preferred_direction == "N":
            pdy = 1
        elif preferred_direction == "S":
            pdy = -1
        elif preferred_direction == "E":
            pdx = 1
        elif preferred_direction == "W":
            pdx = -1
        step = (int(sx) + pdx, int(sy) + pdy)
        if abs(step[0] - int(away[1])) + abs(step[1] - int(away[2])) > current_distance:
            preferred_step = step

    # When a flee direction is latched, keep using it even if blocked.
    if preferred_step is not None:
        candidates = []
        pref_dist = abs(preferred_step[0] - int(away[1])) + abs(preferred_step[1] - int(away[2]))
        candidates.append((pref_dist, preferred_step))
    else:
        directions = list(_DIRECTIONS.keys())
        try:
            rng.shuffle(directions)
        except Exception:
            pass

        candidates: list[tuple[int, tuple[int, int]]] = []
        for dx, dy in directions:
            step = (int(sx) + int(dx), int(sy) + int(dy))
            step_distance = abs(step[0] - int(away[1])) + abs(step[1] - int(away[2]))
            if step_distance <= current_distance:
                continue
            candidates.append((step_distance, step))

    if not candidates:
        _log(ctx, monster, success=False, reason="no-away-step", pos=pos, away=away)
        return False

    # Prefer steps that maximize distance
    candidates.sort(key=lambda value: value[0], reverse=True)

    state = monster.get("_ai_state") if isinstance(monster, Mapping) else None
    pending_target = None
    if isinstance(state, Mapping):
        pending_target = state.get("pending_pursuit")
    has_bound_target = bool(monster.get("target_player_id") or pending_target)

    for _, step in candidates:
        success, details = _apply_movement(
            monster,
            int(year),
            (int(sx), int(sy)),
            step,
            ctx,
            allow_path=preferred_step is None,
        )
        if success:
            meta = {"from": (int(sx), int(sy)), "step": step, "away": away}
            meta.update(details)
            _log(ctx, monster, success=True, reason="flee-step", **meta)
            was_collocated = int(sx) == int(away[1]) and int(sy) == int(away[2])
            try:
                bus = ctx.get("feedback_bus") if isinstance(ctx, Mapping) else getattr(ctx, "feedback_bus", None)
                if hasattr(bus, "push") and isinstance(step, tuple) and len(step) == 2:
                    dx = int(step[0]) - int(sx)
                    dy = int(step[1]) - int(sy)
                    dir_token = None
                    if dx == 1:
                        dir_token = "east"
                    elif dx == -1:
                        dir_token = "west"
                    elif dy == 1:
                        dir_token = "north"
                    elif dy == -1:
                        dir_token = "south"
                    name = _monster_display_name(monster)
                    if was_collocated and dir_token and abs(dx) + abs(dy) > 0:
                        # Guard against duplicate leave/noise in the same tick by tagging ctx.
                        dedupe_key = f"flee_leave::{_monster_id(monster)}"
                        emitted = getattr(ctx, "_flee_emitted", None)
                        if not isinstance(emitted, set):
                            emitted = set()
                            try:
                                setattr(ctx, "_flee_emitted", emitted)
                            except Exception:
                                emitted = None
                        if emitted is None or dedupe_key not in emitted:
                            bus.push("COMBAT/INFO", f"{name} has just left {dir_token}")
                            # Occasional flee noise to better match reference (not every move).
                            noise_ok = True
                            try:
                                noise_ok = int(rng.randrange(100)) < 65
                            except Exception:
                                noise_ok = True
                            if noise_ok:
                                _emit_arrival_and_noise(
                                    ctx,
                                    [int(year), int(step[0]), int(step[1])],
                                    away,
                                    movement=(dx, dy),
                                    flee_mode=True,
                                    has_bound_target=has_bound_target,
                                    rng=rng,
                                    arrived_dir=None,
                                    force_direction=dir_token,
                                )
                            if emitted is not None:
                                emitted.add(dedupe_key)
            except Exception:
                LOG.debug("Failed to push flee leave cue", exc_info=True)
            try:
                monster_pos = monster.get("pos")
            except Exception:  # pragma: no cover - defensive
                monster_pos = None
            movement: tuple[int, int] | None = None
            try:
                if isinstance(step, tuple) and len(step) == 2:
                    movement = (int(step[0]) - int(sx), int(step[1]) - int(sy))
            except Exception:
                movement = None
            # Emit generic flee noise/footsteps even when not previously collocated.
            try:
                _emit_arrival_and_noise(
                    ctx,
                    monster_pos,
                    away,
                    movement=movement,
                    flee_mode=True,
                    has_bound_target=has_bound_target,
                    rng=rng,
                )
            except Exception:
                LOG.debug("Failed to emit flee footsteps", exc_info=True)
            # Suppress shadows on the next frame only when we just left the player's tile,
            # so we don't leak a shadow hint while exiting.
            try:
                if was_collocated:
                    setattr(ctx, "_suppress_shadows_once", "collocated_leave")
            except Exception:
                pass
            # If the monster just moved into the player's tile, emit arrival direction.
            monster_pos = combat_loot.coerce_pos(monster_pos)
            player_pos = combat_loot.coerce_pos(away)
            if monster_pos and player_pos and int(monster_pos[0]) == int(player_pos[0]) and tuple(monster_pos[1:]) == tuple(player_pos[1:]):
                prev_dx = int(sx) - int(player_pos[1])
                prev_dy = int(sy) - int(player_pos[2])
                dir_token = None
                if prev_dx == 1:
                    dir_token = "east"
                elif prev_dx == -1:
                    dir_token = "west"
                elif prev_dy == 1:
                    dir_token = "north"
                elif prev_dy == -1:
                    dir_token = "south"
                bus = ctx.get("feedback_bus") if isinstance(ctx, Mapping) else getattr(ctx, "feedback_bus", None)
                name = _monster_display_name(monster)
                if dir_token and hasattr(bus, "push"):
                    try:
                        bus.push("COMBAT/INFO", f"{name} has just arrived from the {dir_token}.")
                        _emit_arrival_and_noise(
                            ctx,
                            monster_pos,
                            player_pos,
                            movement=movement,
                            flee_mode=True,
                            arrived_dir=dir_token,
                        )
                    except Exception:
                        LOG.debug("Failed to push arrival cue", exc_info=True)
            return True

    _log(ctx, monster, success=False, reason="blocked", attempts=len(candidates), away=away)
    return False


__all__ = ["attempt_pursuit", "attempt_flee_step"]
