from __future__ import annotations
import sys
import logging
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Mapping, Optional

from mutants.util.directions import resolve_dir
from mutants.engine import session as session_state
from mutants.services import monster_ai
from mutants.debug import turnlog
from mutants.commands._helpers import advance_invalid_command_turn


class Dispatch:
    """
    Command router with case-insensitive matching and ≥3-letter unique prefix resolution.
    <3-letter tokens are accepted only if explicitly aliased (e.g., 'n','s','e','w').
    """

    def __init__(self) -> None:
        self._cmds: Dict[str, Callable[[str], None]] = {}
        self._aliases: Dict[str, str] = {}
        self._bus = None  # optional feedback bus
        self._ctx: Any | None = None
        self._log = logging.getLogger(__name__)

    # Optional: REPL can call this after building ctx.
    def set_feedback_bus(self, bus) -> None:
        self._bus = bus

    def set_context(self, ctx: Any) -> None:
        """Remember the REPL context so session metadata can be injected."""

        self._ctx = ctx

    def _warn(self, msg: str) -> None:
        if self._bus is not None:
            self._bus.push("SYSTEM/WARN", msg)
        else:
            print(msg, file=sys.stderr)

    def _post_command(self, token: str, resolved: Optional[str], *, skip_ai: bool = False) -> None:
        if self._ctx is None:
            return
        if not skip_ai:
            try:
                monster_ai.on_player_command(self._ctx, token=token, resolved=resolved)
            except Exception:  # pragma: no cover - defensive
                self._log.exception("Monster AI turn tick failed")
        observer = turnlog.get_observer(self._ctx)
        if observer:
            observer.finish_turn(self._ctx, token, resolved)

    def _resolve_scheduler(self) -> Any | None:
        ctx = self._ctx
        scheduler: Any | None = None
        if isinstance(ctx, Mapping):
            scheduler = ctx.get("turn_scheduler")
        elif ctx is not None:
            scheduler = getattr(ctx, "turn_scheduler", None)
        if scheduler is None:
            scheduler = session_state.get_turn_scheduler()
        if scheduler is None:
            return None
        tick_fn = getattr(scheduler, "tick", None)
        return scheduler if callable(tick_fn) else None

    def _inject_session_context(self) -> None:
        if self._ctx is None:
            return

        active_class = session_state.get_active_class()

        if hasattr(self._ctx, "session"):
            session_obj = getattr(self._ctx, "session")
            if isinstance(session_obj, dict):
                session_obj["active_class"] = active_class
            elif isinstance(session_obj, SimpleNamespace):
                session_obj.active_class = active_class
            elif session_obj is None:
                namespace = SimpleNamespace(active_class=active_class)
                try:
                    setattr(self._ctx, "session", namespace)
                except Exception:
                    namespace = None
                if namespace is not None:
                    session_obj = namespace

        if isinstance(self._ctx, dict):
            session_dict = self._ctx.get("session")
            if not isinstance(session_dict, dict):
                session_dict = {}
                self._ctx["session"] = session_dict
            session_dict["active_class"] = active_class

    def register(self, name: str, fn: Callable[[str], None]) -> None:
        self._cmds[name.lower()] = fn

    def alias(self, alias: str, target: str) -> None:
        self._aliases[alias.lower()] = target.lower()

    def list_commands(self) -> List[str]:
        return sorted(self._cmds.keys())

    def _resolve_prefix(self, token: str) -> Optional[str]:
        t = (token or "").lower()
        # Exact alias (works for 1-letter movement)
        if t in self._aliases:
            return self._aliases[t]
        # ≥3 letters → unique prefix over canonical names and their aliases
        if len(t) >= 3:
            candidates = set()
            # Canonical names
            for name in self._cmds:
                if name.startswith(t):
                    candidates.add(name)
            # Aliases
            for a, target in self._aliases.items():
                if a.startswith(t):
                    candidates.add(target)
            if len(candidates) == 1:
                return next(iter(candidates))
            if len(candidates) > 1:
                pretty = ", ".join(sorted(candidates))
                self._warn(f'Ambiguous command "{token}" (did you mean: {pretty})')
                return None
        # <3 letters without explicit alias, or unknown ≥3 prefix
        self._warn(f'Unknown command "{token}" (commands require at least 3 letters).')
        return None

    def call(self, token: str, arg: str) -> Optional[str]:
        resolved: Optional[str] = None
        result_token: Optional[str] = None
        observer = turnlog.get_observer(self._ctx) if self._ctx is not None else None
        scheduler = self._resolve_scheduler()

        def _dispatch_command(name: str) -> None:
            nonlocal resolved, result_token, skip_ai

            fn = self._cmds.get(name)
            if not fn:
                self._warn(f'Command handler missing for "{name}".')
                handled = advance_invalid_command_turn(self._ctx, token, resolved=name)
                if handled:
                    skip_ai = True
                return

            resolved = name
            result_token = name

            def _player_action() -> tuple[str, Optional[str]]:
                if observer:
                    observer.begin_turn(self._ctx, token, resolved)
                self._inject_session_context()
                fn(arg)
                return token, resolved

            if scheduler is not None:
                scheduler.tick(_player_action)
            else:
                _player_action()

        skip_ai = scheduler is not None
        try:
            dir_name = resolve_dir(token)
            if dir_name and dir_name in self._cmds:
                _dispatch_command(dir_name)
                return result_token

            name = self._resolve_prefix(token)
            if not name:
                handled = advance_invalid_command_turn(self._ctx, token)
                if handled:
                    skip_ai = True
                return result_token

            _dispatch_command(name)
            return result_token
        finally:
            self._post_command(token, resolved, skip_ai=skip_ai)

        return result_token
