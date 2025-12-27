from __future__ import annotations

from typing import Any

from collections.abc import Mapping

import logging

from mutants.services import monsters_state, player_state as pstate
from mutants.ui.class_menu import render_menu


LOG = logging.getLogger(__name__)


def open_menu(ctx: dict[str, Any]) -> None:
    try:
        pstate.clear_target(reason="class-menu")
        monsters_obj = ctx.get("monsters") if isinstance(ctx, Mapping) else None
        try:
            # Persist any monsters before we drop/reload caches so we don't lose spawns.
            if hasattr(monsters_obj, "mark_dirty") and callable(monsters_obj.mark_dirty):
                monsters_obj.mark_dirty(None)  # dirty-all to force a flush of in-memory spawns
            if hasattr(monsters_obj, "save") and callable(monsters_obj.save):
                monsters_obj.save()
        except Exception:
            LOG.debug("Failed to save monsters before class menu open", exc_info=True)
        monsters_state.clear_all_targets(monsters_obj)
        # Reset monsters cache to avoid cross-year bleed when returning to the menu.
        try:
            monsters_state.invalidate_cache()
            ctx["monsters"] = monsters_state.load_state()
        except Exception:
            LOG.debug("Failed to reload monsters cache on class menu open", exc_info=True)
        # Also clear any ready/target state in the live runtime copy.
        runtime = ctx.get("player_state") if isinstance(ctx, Mapping) else None
        if isinstance(runtime, Mapping):
            runtime = dict(runtime)
            runtime["ready_target"] = None
            runtime["target_monster_id"] = None
            if isinstance(runtime.get("ready_target_by_class"), dict):
                for k in list(runtime["ready_target_by_class"].keys()):
                    runtime["ready_target_by_class"][k] = None
            if isinstance(runtime.get("target_monster_id_by_class"), dict):
                for k in list(runtime["target_monster_id_by_class"].keys()):
                    runtime["target_monster_id_by_class"][k] = None
            ctx["player_state"] = runtime
        # Persist immediately so the cleared target survives menu navigation.
        try:
            pstate.save_player_state(ctx)
        except Exception:
            LOG.debug("Failed to persist target clear on menu", exc_info=True)
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to clear ready target when entering class menu")
    ctx["mode"] = "class_select"
    # Clear any pending room render while showing the menu
    ctx["render_next"] = False
    render_menu(ctx)


def register(dispatch, ctx) -> None:
    # Real command name (>=3 chars) + single-letter alias 'x'
    dispatch.register("menu", lambda arg: open_menu(ctx))
    dispatch.alias("x", "menu")
