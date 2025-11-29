from __future__ import annotations

import logging
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, Iterable, MutableMapping, Optional

from mutants.registries.world import load_nearest_year
from mutants.services import monsters_state, player_state as pstate
from mutants.state import state_path
from ..services import item_transfer as itx
from ..services import state_debug


ION_COST_PER_CENTURY = 3000


def _update_runtime_state(ctx: MutableMapping[str, Any], state: Mapping[str, Any]) -> None:
    """Store ``state`` in ``ctx`` and rebuild the runtime player snapshot."""

    ctx["player_state"] = dict(state)
    try:
        pstate.ensure_player_state(ctx)
    except Exception:
        # Runtime snapshots are best-effort; avoid crashing travel when optional
        # context isn't available (e.g., in batch tests).
        pass
    # ensure_player_state can strip the transient "active" view; rebuild a
    # fresh runtime snapshot so callers always have one.
    active_view = pstate.build_active_view(ctx.get("player_state") or {})
    if active_view:
        ctx["player_state"]["active"] = active_view
        ctx["_runtime_player"] = active_view


def _floor_to_century(year: int) -> int:
    """Return the start of the century for ``year`` (e.g., 2314 -> 2300)."""

    return (int(year) // 100) * 100


def _parse_year(arg: str) -> Optional[int]:
    """Extract the first integer value from ``arg`` if possible."""

    if arg is None:
        return None
    s = arg.strip()
    if not s:
        return None
    sign = 1
    if s[0] in {"+", "-"}:
        if s[0] == "-":
            sign = -1
        s = s[1:]
    digits: list[str] = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    if not digits:
        return None
    return sign * int("".join(digits))


def _century_index(year: int) -> int:
    return (int(year) // 100) + 1


def _available_years(ctx: Dict[str, Any]) -> list[int]:
    """Return sorted available world years."""

    years = ctx.get("world_years")
    if callable(years):
        try:
            years = years()
        except Exception:
            years = None

    iterable: Optional[Iterable[Any]]
    if isinstance(years, Iterable) and not isinstance(years, (str, bytes)):
        iterable = years
    else:
        iterable = None

    sanitized: list[int] = []
    if iterable is not None:
        for raw in iterable:
            if isinstance(raw, Path):
                raw = raw.stem
            try:
                sanitized.append(int(raw))
            except Exception:
                continue
    else:
        default_world_dir = state_path("world")
        base_dir = ctx.get("world_dir", default_world_dir)
        try:
            base_path = Path(base_dir)
        except TypeError:
            base_path = default_world_dir
        if base_path.exists():
            for fpath in base_path.glob("*.json"):
                try:
                    sanitized.append(int(fpath.stem))
                except Exception:
                    continue
    return sorted(set(sanitized))


def _resolved_year(ctx: Dict[str, Any], target: int) -> Optional[int]:
    loader = ctx.get("world_loader", load_nearest_year)
    try:
        world = loader(int(target))
    except FileNotFoundError:
        ctx["feedback_bus"].push(
            "SYSTEM/ERROR",
            f"No worlds found in {state_path('world')}/.",
        )
        return None
    return int(getattr(world, "year", int(target)))


def _persist_pos_only(
    resolved_year: int, ctx: MutableMapping[str, Any]
) -> Optional[Dict[str, Any]]:
    """Write only the active player's position to canonical state."""

    try:
        loaded = pstate.load_state()
    except Exception:
        loaded = None

    state = ctx.get("player_state")
    canonical_state: MutableMapping[str, Any]
    if isinstance(loaded, MutableMapping):
        canonical_state = loaded
    elif isinstance(loaded, Mapping):
        canonical_state = dict(loaded)
    elif isinstance(state, MutableMapping):
        canonical_state = state
    elif isinstance(state, Mapping):
        canonical_state = dict(state)
    else:
        return None

    cur_year, cur_x, cur_y = pstate.canonical_player_pos(canonical_state)
    delta = (resolved_year - cur_year, -cur_x, -cur_y)
    new_pos = pstate.move_player(
        canonical_state, pstate.get_active_class(canonical_state), delta
    )

    try:
        pstate.save_state(canonical_state, reason="time-travel")
    except Exception:
        return None

    try:
        refreshed = pstate.load_state()
    except Exception:
        refreshed = canonical_state

    if isinstance(refreshed, Mapping) and not isinstance(refreshed, dict):
        refreshed = dict(refreshed)

    if isinstance(refreshed, dict):
        pstate.normalize_player_state_inplace(refreshed)
        _update_runtime_state(ctx, refreshed)
        pstate.sync_runtime_position(ctx, new_pos)

    return refreshed if isinstance(refreshed, dict) else None


def travel_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    bus = ctx["feedback_bus"]

    def _clear_monster_targets() -> None:
        """Drop monster aggro when jumping between centuries."""

        try:
            monsters_obj = None
            if isinstance(ctx, Mapping):
                candidate = ctx.get("monsters")
                if hasattr(candidate, "list_all"):
                    monsters_obj = candidate
            monsters_state.clear_all_targets(monsters_obj)
        except Exception:  # pragma: no cover - defensive guard
            LOG.exception("Failed to clear monster targets after time travel")

    year_raw = _parse_year(arg or "")
    if year_raw is None:
        bus.push("SYSTEM/WARN", "Usage: TRAVEL <year>  (e.g., 'tra 2100').")
        return

    dest_century = _floor_to_century(year_raw)
    available = _available_years(ctx)
    if available and dest_century > max(available):
        bus.push("SYSTEM/WARN", "That year doesn't exist yet!")
        return
    if not available:
        bus.push("SYSTEM/WARN", "That year doesn't exist yet!")
        return

    player = pstate.ensure_player_state(ctx)
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)
    start_year, start_x, start_y = pstate.canonical_player_pos(player)
    start_pos = [start_year, start_x, start_y]
    # Always operate on a fresh canonical state for currency to avoid stale ctx copies.
    try:
        loaded_state = pstate.load_state()
    except Exception:
        currency_state: Dict[str, Any] = {}
    else:
        if isinstance(loaded_state, dict):
            currency_state = loaded_state
        elif isinstance(loaded_state, Mapping):
            currency_state = dict(loaded_state)
        else:
            currency_state = {}

    try:
        ions_balance = pstate.get_ions_for_active(currency_state)
    except Exception:
        ions_balance = 0

    # Debug logger (same as CONVERT uses). Only emits when playersdbg is enabled.
    LOG_P = logging.getLogger("playersdbg")
    if pstate._pdbg_enabled():  # pragma: no cover - diagnostic hook
        pstate._pdbg_setup_file_logging()
        try:
            LOG_P.info(
                "[playersdbg] TRAVEL start active_id=%s class=%s pos=%s",
                currency_state.get("active_id"),
                pstate.get_active_class(currency_state),
                list(pstate.canonical_player_pos(currency_state)),
            )
        except Exception:
            pass

    def _update_ions(new_amount: int) -> int:
        """Persist ions for the active class (fresh state-in, fresh state-out)."""

        nonlocal currency_state
        # Persist via helper (updates per-class map + mirrors the in-memory view).
        before_cls = pstate.get_active_class(currency_state)
        before_ions = pstate.get_ions_for_active(currency_state)
        result = pstate.set_ions_for_active(currency_state, new_amount)
        # Reload to keep ctx in sync for subsequent reads in this command.
        try:
            reloaded_state = pstate.load_state()
        except Exception:
            pass
        else:
            if isinstance(reloaded_state, dict):
                currency_state = reloaded_state
            elif isinstance(reloaded_state, Mapping):
                currency_state = dict(reloaded_state)
        if pstate._pdbg_enabled():  # pragma: no cover - diagnostic hook
            try:
                after_cls = pstate.get_active_class(currency_state)
                after_ions = pstate.get_ions_for_active(currency_state)
                LOG_P.info(
                    "[playersdbg] TRAVEL write ions class=%s->%s before=%s write=%s after=%s",
                    before_cls,
                    after_cls,
                    before_ions,
                    new_amount,
                    after_ions,
                )
            except Exception:
                pass
        player["ions"] = result
        player["Ions"] = result
        active_profile = player.get("active")
        if isinstance(active_profile, dict):
            active_profile["ions"] = result
            active_profile["Ions"] = result
        return result

    current_year, _, _ = pstate.canonical_player_pos(ctx.get("player_state"))
    current_century = _floor_to_century(current_year)

    if dest_century == current_century:
        resolved_year = _resolved_year(ctx, dest_century)
        if resolved_year is None:
            return
        new_state = _persist_pos_only(resolved_year, ctx)
        if isinstance(new_state, Mapping):
            _update_runtime_state(ctx, new_state)
            if "render_next" in ctx:
                ctx["render_next"] = False
        bus.push(
            "SYSTEM/OK",
            f"You're already in the {_century_index(dest_century)}th Century!",
        )
        state_debug.log_travel(
            ctx,
            command="travel",
            arg=arg,
            from_pos=start_pos,
            to_pos=[resolved_year, 0, 0],
            ions_before=ions_balance,
            ions_after=ions_balance,
        )
        return

    steps = abs(dest_century - current_century) // 100
    full_cost = steps * ION_COST_PER_CENTURY
    # Read ions strictly from per-class storage for the active class.
    ions = ions_balance
    if pstate._pdbg_enabled():  # pragma: no cover - diagnostic hook
        try:
            LOG_P.info(
                "[playersdbg] TRAVEL cost class=%s steps=%s cost=%s ions_before=%s",
                pstate.get_active_class(currency_state),
                steps,
                full_cost,
                ions,
            )
        except Exception:
            pass

    if ions < ION_COST_PER_CENTURY:
        bus.push("SYSTEM/WARN", "You don't have enough ions to create a portal.")
        if pstate._pdbg_enabled():  # pragma: no cover
            try:
                LOG_P.info(
                    "[playersdbg] TRAVEL abort reason=insufficient ions=%s min_cost=%s",
                    ions,
                    ION_COST_PER_CENTURY,
                )
            except Exception:
                pass
        return

    if ions >= full_cost:
        resolved_year = _resolved_year(ctx, dest_century)
        if resolved_year is None:
            return
        new_total = ions - full_cost
        _update_ions(new_total)
        maybe_state = _persist_pos_only(resolved_year, ctx)
        if isinstance(maybe_state, Mapping):
            _update_runtime_state(ctx, maybe_state)
            if "render_next" in ctx:
                ctx["render_next"] = False
        if pstate._pdbg_enabled():  # pragma: no cover
            try:
                LOG_P.info(
                    "[playersdbg] TRAVEL full_move resolved=%s ions_after=%s",
                    resolved_year,
                    pstate.get_ions_for_active(currency_state),
                )
            except Exception:
                pass
        try:
            ions_after = pstate.get_ions_for_active(currency_state)
        except Exception:
            ions_after = new_total
        state_debug.log_travel(
            ctx,
            command="travel",
            arg=arg,
            from_pos=start_pos,
            to_pos=[resolved_year, 0, 0],
            ions_before=ions,
            ions_after=ions_after,
        )
        _clear_monster_targets()
        bus.push(
            "SYSTEM/OK",
            f"ZAAAPPPPP!! You've been sent to the year {resolved_year} A.D.",
        )
        return

    min_century = min(current_century, dest_century)
    max_century = max(current_century, dest_century)
    candidates = [year for year in available if min_century <= year <= max_century]
    if not candidates:
        # Spend everything we can to get as far as possible (as before), then persist.
        ions_after = _update_ions(0)
        maybe_state = _persist_pos_only(current_century, ctx)
        if isinstance(maybe_state, Mapping):
            _update_runtime_state(ctx, maybe_state)
            if "render_next" in ctx:
                ctx["render_next"] = False
        if pstate._pdbg_enabled():  # pragma: no cover
            try:
                LOG_P.info(
                    "[playersdbg] TRAVEL partial_move candidates=0 ions_after=%s",
                    pstate.get_ions_for_active(currency_state),
                )
            except Exception:
                pass
        state_debug.log_travel(
            ctx,
            command="travel",
            arg=arg,
            from_pos=start_pos,
            to_pos=[current_century, 0, 0],
            ions_before=ions,
            ions_after=ions_after,
        )
        _clear_monster_targets()
        bus.push(
            "SYSTEM/WARN",
            "ZAAAPPPP!!!! You suddenly feel something has gone terribly wrong!",
        )
        return

    chosen_year = random.choice(candidates)
    resolved_year = _resolved_year(ctx, chosen_year)
    if resolved_year is None:
        return
    ions_after = _update_ions(0)
    maybe_state = _persist_pos_only(resolved_year, ctx)
    if isinstance(maybe_state, Mapping):
        _update_runtime_state(ctx, maybe_state)
        if "render_next" in ctx:
            ctx["render_next"] = False
    state_debug.log_travel(
        ctx,
        command="travel",
        arg=arg,
        from_pos=start_pos,
        to_pos=[resolved_year, 0, 0],
        ions_before=ions,
        ions_after=ions_after,
    )
    _clear_monster_targets()
    bus.push(
        "SYSTEM/WARN",
        "ZAAAPPPP!!!! You suddenly feel something has gone terribly wrong!",
    )


def register(dispatch, ctx) -> None:
    dispatch.register("travel", lambda arg: travel_cmd(arg, ctx))
    
