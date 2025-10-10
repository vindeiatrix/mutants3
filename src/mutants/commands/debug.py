from __future__ import annotations

import logging
import shlex

from ..registries import items_instances as itemsreg
from ..registries import items_catalog
from ..services import player_state as pstate
from ..util.textnorm import normalize_item_query


LOG_P = logging.getLogger("mutants.playersdbg")


def _pos_from_ctx(ctx) -> tuple[int, int, int]:
    state = ctx.get("player_state", {})
    aid = state.get("active_id")
    for pl in state.get("players", []):
        if pl.get("id") == aid:
            pos = pl.get("pos") or [0, 0, 0]
            return int(pos[0]), int(pos[1]), int(pos[2])
    pos = state.get("players", [{}])[0].get("pos") or [0, 0, 0]
    return int(pos[0]), int(pos[1]), int(pos[2])


def _display_name(it: dict) -> str:
    for key in ("display_name", "name", "title"):
        if isinstance(it.get(key), str):
            return it[key]
    return it.get("item_id", "")


def _resolve_item_id(raw: str, catalog):
    q = normalize_item_query(raw)
    q_id = q.replace("-", "_")
    if catalog.get(q_id):
        return q_id, None
    prefix = [iid for iid in catalog._by_id if iid.startswith(q_id)]
    if len(prefix) == 1:
        return prefix[0], None
    if len(prefix) > 1:
        return None, prefix
    name_matches = []
    for it in catalog._items_list:
        if normalize_item_query(_display_name(it)) == q:
            name_matches.append(it["item_id"])
    if len(name_matches) == 1:
        return name_matches[0], None
    if len(name_matches) > 1:
        return None, name_matches
    return None, []



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
    spawned, pos = _spawn_items_at_player(ctx, item_id, count)
    preview = ", ".join(spawned[:5])
    if len(spawned) > 5:
        preview = f"{preview}, …"
    bus.push(
        "DEBUG",
        f"spawned {count} x {item_id} at ({pos[0]}, {pos[1]}, {pos[2]}) [{preview}]",
    )


def debug_cmd(arg: str, ctx):
    parts = shlex.split(arg.strip())
    if not parts:
        ctx["feedback_bus"].push(
            "SYSTEM/INFO",
            "Usage: debug add <item_id> [qty] | debug where | debug count | "
            "debug ions <amount> | debug riblets <amount>",
        )
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

    ctx["feedback_bus"].push(
        "SYSTEM/INFO",
        "Usage: debug add <item_id> [qty] | debug where | debug count | "
        "debug ions <amount> | debug riblets <amount>",
    )


def register(dispatch, ctx) -> None:
    dispatch.register("debug", lambda arg: debug_cmd(arg, ctx))
    dispatch.register("give", lambda arg: debug_add_cmd(arg, ctx))
