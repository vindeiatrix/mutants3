from __future__ import annotations

import logging
import shlex
from typing import Mapping, MutableMapping, Sequence

from mutants.env import debug_commands_enabled
from mutants.services import monster_manual_spawn, player_state as pstate
from mutants.registries import (
    items_catalog,
    items_instances,
    monsters_catalog,
    monsters_instances,
)
from ..util.textnorm import normalize_item_query
from ..services import state_debug


itemsreg = items_instances


LOG_P = logging.getLogger("mutants.playersdbg")


def _pos_from_ctx(ctx) -> tuple[int, int, int]:
    state = ctx.get("player_state", {})
    year, x, y = pstate.canonical_player_pos(state)
    return year, x, y


def _display_name(it: dict) -> str:
    for key in ("display_name", "name", "title"):
        if isinstance(it.get(key), str):
            return it[key]
    return it.get("item_id", "")


def _resolve_item_id(raw: str, catalog):
    q = normalize_item_query(raw)
    if not q:
        return None, []
    q_id = q.replace("-", "_")
    if catalog.get(q_id):
        return q_id, None
    prefix = [iid for iid in catalog._by_id if iid.startswith(q_id)]
    if prefix:
        return prefix[0], None
    name_matches = []
    for it in catalog._items_list:
        norm_name = normalize_item_query(_display_name(it))
        if norm_name.startswith(q):
            name_matches.append(it["item_id"])
    if name_matches:
        return name_matches[0], None
    return None, []


def _resolve_monster_id(raw: str, catalog):
    q = normalize_item_query(raw)
    if not q:
        return None, []
    q_id = q.replace("-", "_")
    if catalog.get(q_id):
        return q_id, None
    prefix = [mid for mid in catalog._by_id if mid.startswith(q_id)]
    if prefix:
        return prefix[0], None
    name_matches = []
    for monster in catalog._list:
        name = monster.get("name") or monster.get("monster_id")
        if normalize_item_query(str(name)).startswith(q):
            name_matches.append(monster.get("monster_id"))
    if name_matches:
        return name_matches[0], None
    return None, []


def _debug_mode_enabled(ctx) -> bool:
    if debug_commands_enabled():
        return True

    if isinstance(ctx, Mapping):
        flag = ctx.get("debug_enabled")
        if flag:
            return True
        services = ctx.get("services")
        if isinstance(services, Mapping) and services.get("debug_enabled"):
            return True

    try:
        attr_flag = getattr(ctx, "debug_enabled")
    except Exception:
        attr_flag = None
    return bool(attr_flag)


def _spawn_items_at_player(
    ctx, item_id: str, count: int
) -> tuple[list[str], tuple[int, int, int]]:
    """Mint ``count`` items at the active player's tile returning the created iids."""

    year, x, y = _pos_from_ctx(ctx)
    spawned: list[str] = []
    for _ in range(count):
        iid = itemsreg.mint_on_ground_with_defaults(
            item_id,
            year=year,
            x=x,
            y=y,
            origin="debug_add",
        )
        spawned.append(iid)
    return spawned, (year, x, y)


def _debug_where(ctx) -> None:
    year, x, y = _pos_from_ctx(ctx)
    ctx["feedback_bus"].push("DEBUG", f"pos=({year}, {x}, {y})")


def _debug_count(ctx) -> None:
    year, x, y = _pos_from_ctx(ctx)
    store = itemsreg._items_store()
    snapshot = list(store.snapshot())
    total = len(snapshot)
    here = len(list(store.list_at(year, x, y)))
    ctx["feedback_bus"].push(
        "DEBUG", f"items total={total} here={here} at ({year}, {x}, {y})"
    )


def _debug_monster(arg: str, ctx) -> None:
    bus = ctx["feedback_bus"]
    monster_id = (arg or "").strip()
    if not monster_id:
        bus.push("SYSTEM/WARN", "Usage: debug monster <monster_id>")
        return

    pos = _pos_from_ctx(ctx)
    coords = [int(pos[0]), int(pos[1]), int(pos[2])]
    player = pstate.ensure_player_state(ctx)
    before_snapshot = state_debug.log_inventory_stage(
        ctx, player, command="debug_monster", arg=arg, stage="inventory_before"
    )

    try:
        mon_cat = monsters_catalog.get()
    except FileNotFoundError:
        bus.push("SYSTEM/WARN", "Monster catalog unavailable.")
        return

    monster_id, _ = _resolve_monster_id(monster_id, mon_cat)
    if not monster_id:
        bus.push("SYSTEM/WARN", f"Unknown monster: {arg}")
        return

    item_reg = items_instances.get()
    try:
        item_cat = items_catalog.get()
    except FileNotFoundError:
        bus.push("SYSTEM/WARN", "Items catalog unavailable.")
        return

    template = mon_cat.get_template(monster_id)
    if not template:
        bus.push("SYSTEM/WARN", f"No monster template found for ID: {monster_id}")
        return

    # Prefer spawning into the in-memory cache so rendering and gameplay
    # immediately see the new monster; the scheduler will flush to store.
    monsters_state_obj = None
    if isinstance(ctx, Mapping):
        candidate = ctx.get("monsters")
        if hasattr(candidate, "add_instance") and hasattr(candidate, "list_all"):
            monsters_state_obj = candidate
    if monsters_state_obj is not None:
        instance = monster_manual_spawn.spawn_monster_into_state(
            monster_id=template.monster_id,
            pos=coords,
            monsters_cat=mon_cat,
            items_cat=item_cat,
            items_reg=item_reg,
            monsters_state_obj=monsters_state_obj,
        )
    else:
        # Fallback: write directly to the store if no cache is available.
        mon_reg = monsters_instances.load_monsters_instances()
        instance = monster_manual_spawn.spawn_monster_at(
            monster_id=template.monster_id,
            pos=coords,
            monsters_cat=mon_cat,
            monsters_reg=mon_reg,
            items_cat=item_cat,
            items_reg=item_reg,
        )

    if instance is None:
        bus.push("SYSTEM/WARN", f"Failed to spawn {monster_id}.")
        return

    name = instance.get("name") or template.name
    state_debug.log_inventory_update(
        ctx,
        player,
        command="debug_monster",
        arg=arg,
        before=before_snapshot,
        extra={"monster_id": monster_id, "pos": coords, "instance_id": instance.get("id")},
    )
    bus.push("SYSTEM/OK", f"Spawned {name} at your location.")
    ctx["render_next"] = True


def _set_currency_for_active(ctx, currency: str, amount: int) -> None:
    """Set a per-class currency to ``amount`` with detailed debug logging."""

    bus = ctx["feedback_bus"]
    state = pstate.load_state()
    cls_name = pstate.get_active_class(state)

    if currency == "ions":
        getter = pstate.get_ions_for_active
        setter = pstate.set_ions_for_active
    elif currency == "riblets":
        getter = pstate.get_riblets_for_active
        setter = pstate.set_riblets_for_active
    else:  # pragma: no cover - defensive guard for future callers
        raise ValueError(f"Unknown currency '{currency}'")

    before = getter(state)
    pstate._check_invariants_and_log(state, f"before debug {currency}")

    if pstate._pdbg_enabled():
        pstate._pdbg_setup_file_logging()
        LOG_P.info(
            "[playersdbg] DEBUG-%s before class=%s %s=%s",
            currency.upper(),
            cls_name,
            currency,
            before,
        )

    setter(state, amount)

    state_after = pstate.load_state()
    after = getter(state_after)

    if pstate._pdbg_enabled():
        LOG_P.info(
            "[playersdbg] DEBUG-%s after  class=%s %s=%s :: %s",
            currency.upper(),
            cls_name,
            currency,
            after,
            pstate._invariants_summary(state_after),
        )

    pstate._check_invariants_and_log(state_after, f"after debug {currency}")
    bus.push("SYSTEM/OK", f"Set {currency} for {cls_name} to {after}.")


def _set_hp_for_active(ctx, amount: int) -> None:
    """Set both current and max HP for the active player to ``amount``."""

    bus = ctx["feedback_bus"]
    state = pstate.load_state()
    cls_name = pstate.get_active_class(state)
    new_hp = max(0, int(amount))
    pstate._check_invariants_and_log(state, "before debug hp")

    hp_block = {"current": new_hp, "max": new_hp}
    updated = pstate.set_hp_for_active(state, hp_block)

    state_after = pstate.load_state()
    pstate._check_invariants_and_log(state_after, "after debug hp")

    # Keep the live ctx in sync so subsequent actions use the new HP values.
    if isinstance(ctx, MutableMapping):
        ctx["player_state"] = state_after
        runtime = ctx.get(pstate._RUNTIME_PLAYER_KEY)  # type: ignore[attr-defined]
        if isinstance(runtime, MutableMapping):
            runtime["hp"] = dict(updated)
            runtime["_dirty"] = True
        state_hint = ctx.get("player_state")
        if isinstance(state_hint, MutableMapping):
            state_hint["hp"] = dict(updated)
            hp_by = state_hint.setdefault("hp_by_class", {})
            hp_by[pstate.get_active_class(state_after)] = dict(updated)

    bus.push("SYSTEM/OK", f"Set HP for {cls_name} to {updated['current']} / {updated['max']}.")


def debug_add_cmd(arg: str, ctx):
    parts = shlex.split(arg.strip())
    bus = ctx["feedback_bus"]
    if not parts:
        bus.push("SYSTEM/INFO", "Usage: debug add <item_id> [qty]")
        return
    catalog = items_catalog.load_catalog()
    item_arg = parts[0]
    item_id, matches = _resolve_item_id(item_arg, catalog)
    if not item_id:
        if matches:
            bus.push(
                "SYSTEM/WARN",
                f"Ambiguous item ID: \"{item_arg}\" matches {', '.join(matches)}.",
            )
        else:
            bus.push("SYSTEM/WARN", f"Unknown item: {item_arg}")
        return
    try:
        count = int(parts[1]) if len(parts) >= 2 else 1
    except Exception:
        count = 1
    count = max(1, min(99, count))
    player = pstate.ensure_player_state(ctx)
    before_snapshot = state_debug.log_inventory_stage(
        ctx, player, command="debug_add", arg=arg, stage="inventory_before"
    )
    spawned, pos = _spawn_items_at_player(ctx, item_id, count)
    preview = ", ".join(spawned[:5])
    if len(spawned) > 5:
        preview = f"{preview}, …"
    state_debug.log_inventory_update(
        ctx,
        player,
        command="debug_add",
        arg=arg,
        before=before_snapshot,
        extra={"spawned": spawned, "pos": list(pos)},
    )
    bus.push(
        "DEBUG",
        f"spawned {count} x {item_id} at ({pos[0]}, {pos[1]}, {pos[2]}) [{preview}]",
    )


def debug_cmd(arg: str, ctx):
    parts = shlex.split(arg.strip())
    if not parts:
        ctx["feedback_bus"].push(
            "SYSTEM/INFO",
            "Usage: debug add <item_id> [qty] | debug monster <monster_id> | "
            "debug where | debug count | debug ions <amount> | debug riblets <amount> | debug hp <amount>",
        )
        return

    if parts[0] == "monster":
        monster_id = parts[1] if len(parts) >= 2 else ""
        _debug_monster(monster_id, ctx)
        return

    if parts[0] == "add":
        debug_add_cmd(" ".join(parts[1:]), ctx)
        return

    if parts[0] == "where":
        _debug_where(ctx)
        return

    if parts[0] == "count":
        _debug_count(ctx)
        return

    if parts[0] in {"ions", "ion"}:
        if len(parts) < 2:
            ctx["feedback_bus"].push(
                "SYSTEM/INFO", "Usage: debug ions <amount>"
            )
            return
        try:
            amount = int(parts[1])
        except ValueError:
            ctx["feedback_bus"].push(
                "SYSTEM/WARN", "Ion amount must be an integer (e.g. 100 or -25)."
            )
            return
        _set_currency_for_active(ctx, "ions", amount)
        return

    if parts[0] in {"riblets", "riblet", "rib"}:
        if len(parts) < 2:
            ctx["feedback_bus"].push(
                "SYSTEM/INFO", "Usage: debug riblets <amount>"
            )
            return
        try:
            amount = int(parts[1])
        except ValueError:
            ctx["feedback_bus"].push(
                "SYSTEM/WARN", "Riblet amount must be an integer (e.g. 50)."
            )
            return
        _set_currency_for_active(ctx, "riblets", amount)
        return

    if parts[0] == "hp":
        if len(parts) < 2:
            ctx["feedback_bus"].push(
                "SYSTEM/INFO", "Usage: debug hp <amount>"
            )
            return
        try:
            amount = int(parts[1])
        except ValueError:
            ctx["feedback_bus"].push(
                "SYSTEM/WARN", "HP amount must be an integer (e.g. 1000)."
            )
            return
        _set_hp_for_active(ctx, amount)
        return

    ctx["feedback_bus"].push(
        "SYSTEM/INFO",
        "Usage: debug add <item_id> [qty] | debug monster <monster_id> | "
        "debug where | debug count | debug ions <amount> | debug riblets <amount> | debug hp <amount>",
    )


_DEBUG_HELP_ENTRIES: Sequence[str] = (
    "debug add <item_id> [qty]",
    "debug monster <monster_id>",
    "debug where",
    "debug count",
    "debug ions <amount>",
    "debug riblets <amount>",
    "debug hp <amount>",
)


def render_debug_help() -> str:
    lines = ["Debug commands:"]
    for entry in _DEBUG_HELP_ENTRIES:
        lines.append(f" - {entry}")
    return "\n".join(lines)


def register(dispatch, ctx) -> None:
    dispatch.register("debug", lambda arg: debug_cmd(arg, ctx))
    dispatch.register("give", lambda arg: debug_add_cmd(arg, ctx))
