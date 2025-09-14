from __future__ import annotations
import sys
from typing import Callable, Dict, List, Optional

from mutants.util.directions import resolve_dir


class Dispatch:
    """
    Command router with case-insensitive matching and ≥3-letter unique prefix resolution.
    <3-letter tokens are accepted only if explicitly aliased (e.g., 'n','s','e','w').
    """

    def __init__(self) -> None:
        self._cmds: Dict[str, Callable[[str], None]] = {}
        self._aliases: Dict[str, str] = {}
        self._bus = None  # optional feedback bus

    # Optional: REPL can call this after building ctx.
    def set_feedback_bus(self, bus) -> None:
        self._bus = bus

    def _warn(self, msg: str) -> None:
        if self._bus is not None:
            self._bus.push("SYSTEM/WARN", msg)
        else:
            print(msg, file=sys.stderr)

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
        dir_name = resolve_dir(token)
        if dir_name and dir_name in self._cmds:
            fn = self._cmds.get(dir_name)
            if fn:
                fn(arg)
            return dir_name
        name = self._resolve_prefix(token)
        if not name:
            return None
        fn = self._cmds.get(name)
        if not fn:
            self._warn(f'Command handler missing for "{name}".')
            return None
        fn(arg)
        return name
