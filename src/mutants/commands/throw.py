from __future__ import annotations
from typing import Dict, Any
from .argcmd import PosArg, PosArgSpec, run_argcmd_positional
from ..services import item_transfer as itx


def _do_throw(ctx: Dict[str, Any], dir: str, item: str) -> Dict[str, Any]:
    return itx.throw_to_neighbor(ctx, dir, item)


def throw_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    spec = PosArgSpec(
        verb="THROW",
        args=[PosArg("dir", "direction"), PosArg("item", "item_in_inventory")],
        messages={
            "usage": "Type THROW [direction] [item].",
            "invalid": "You can't throw that way.",
            "success": "You throw the {item} {dir}.",
        },
        reason_messages={
            "invalid_direction": "That isn't a valid direction.",
            "not_carrying": "You're not carrying a {item}.",
            "not_found": "You're not carrying a {item}.",
            "inventory_empty": "You have nothing to throw.",
            "armor_cannot_drop": "You can't throw what you're wearing.",
            "no_target_tile": "You can't throw that way.",
        },
        success_kind="COMBAT/THROW",
        warn_kind="SYSTEM/WARN",
    )

    run_argcmd_positional(ctx, spec, arg, lambda **kw: _do_throw(ctx, **kw))


def register(dispatch, ctx) -> None:
    dispatch.register("throw", lambda arg: throw_cmd(arg, ctx))

