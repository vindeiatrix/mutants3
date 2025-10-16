from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, MutableMapping, Optional

from mutants.debug import turnlog
from mutants.services import monster_ai
from mutants.services import random_pool

LOG = logging.getLogger(__name__)

__all__ = ["TurnScheduler"]

_MISSING = object()


class TurnScheduler:
    """Coordinate deterministic turn ticks between players and monsters."""

    def __init__(self, ctx: Any, *, rng_name: str = "turn") -> None:
        self._ctx = ctx
        self._rng_name = rng_name

    def tick(self, player_action: Callable[[], Any]) -> None:
        """Advance the shared tick counter and resolve a full turn."""

        tick_id = random_pool.advance_rng_tick(self._rng_name)
        self._log_tick(tick_id)

        rng = random_pool.get_rng(self._rng_name)
        restore_token = self._inject_rng(rng)

        try:
            result = player_action()
            token, resolved = self._normalize_result(result)
            self._run_monster_turns(token, resolved)
        finally:
            self._restore_rng(restore_token)

    # Internal helpers -------------------------------------------------
    def _normalize_result(self, result: Any) -> tuple[str, Optional[str]]:
        token = ""
        resolved: Optional[str] = None

        if isinstance(result, tuple):
            if result:
                raw_token = result[0]
                if raw_token is not None:
                    token = str(raw_token)
            if len(result) > 1:
                raw_resolved = result[1]
                if raw_resolved is not None:
                    resolved = str(raw_resolved)
        elif isinstance(result, Mapping):
            raw_token = result.get("token")
            raw_resolved = result.get("resolved")
            if raw_token is not None:
                token = str(raw_token)
            if raw_resolved is not None:
                resolved = str(raw_resolved)
        elif result is not None:
            token = str(result)

        return token, resolved

    def _inject_rng(self, rng: Any) -> tuple[str, object]:
        ctx = self._ctx
        if isinstance(ctx, MutableMapping):
            previous = ctx.get("monster_ai_rng", _MISSING)
            ctx["monster_ai_rng"] = rng
            return ("mapping", previous)
        try:
            previous = getattr(ctx, "monster_ai_rng", _MISSING)
            setattr(ctx, "monster_ai_rng", rng)
        except Exception:  # pragma: no cover - defensive
            return ("none", _MISSING)
        return ("attr", previous)

    def _restore_rng(self, token: tuple[str, object]) -> None:
        kind, previous = token
        ctx = self._ctx
        if kind == "mapping":
            mapping = ctx if isinstance(ctx, MutableMapping) else None
            if mapping is None:
                return
            if previous is _MISSING:
                mapping.pop("monster_ai_rng", None)
            else:
                mapping["monster_ai_rng"] = previous
        elif kind == "attr":
            if previous is _MISSING:
                try:
                    delattr(ctx, "monster_ai_rng")
                except Exception:  # pragma: no cover - defensive
                    pass
            else:
                try:
                    setattr(ctx, "monster_ai_rng", previous)
                except Exception:  # pragma: no cover - defensive
                    pass
        else:  # "none" or unknown token; nothing to restore.
            return

    def _run_monster_turns(self, token: str, resolved: Optional[str]) -> None:
        try:
            monster_ai.on_player_command(self._ctx, token=token, resolved=resolved)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("Monster AI turn tick failed")

    def _log_tick(self, tick_id: int) -> None:
        message = f"tick={tick_id}"
        turnlog.emit(self._ctx, "TURN/TICK", message=message, tick=tick_id)
        LOG.info("TURN/TICK %s", message)
