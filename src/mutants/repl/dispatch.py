from __future__ import annotations
import sys
import logging
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Any

from mutants.util.directions import resolve_dir
from mutants.engine import session as session_state
from mutants.services import monster_ai
from mutants.debug import turnlog


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

    def _post_command(self, token: str, resolved: Optional[str]) -> None:
        if self._ctx is None:
            return
        try:
            monster_ai.on_player_command(self._ctx, token=token, resolved=resolved)
        except Exception:  # pragma: no cover - defensive
            self._log.exception("Monster AI turn tick failed")
        observer = turnlog.get_observer(self._ctx)
        if observer:
            observer.finish_turn(self._ctx, token, resolved)

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
        dir_name = resolve_dir(token)
        observer = turnlog.get_observer(self._ctx) if self._ctx is not None else None
        try:
            if dir_name and dir_name in self._cmds:
                fn = self._cmds.get(dir_name)
                resolved = dir_name
                if fn:
                    if observer:
                        observer.begin_turn(self._ctx, token, resolved)
                    self._inject_session_context()
                    fn(arg)
                return dir_name
            name = self._resolve_prefix(token)
            if not name:
                return None
            fn = self._cmds.get(name)
            if not fn:
                self._warn(f'Command handler missing for "{name}".')
                return None
            resolved = name
            if observer:
                observer.begin_turn(self._ctx, token, resolved)
            self._inject_session_context()
            fn(arg)
            return name
        finally:
            self._post_command(token, resolved)
