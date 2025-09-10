from __future__ import annotations

from typing import Callable, Dict


class Dispatch:
    def __init__(self, bus) -> None:
        self._cmds: Dict[str, Callable[[str], None]] = {}
        self._alias: Dict[str, str] = {}
        self._bus = bus

    def register(self, name: str, fn: Callable[[str], None]) -> None:
        self._cmds[name.lower()] = fn

    def alias(self, alias_name: str, canonical: str) -> None:
        self._alias[alias_name.lower()] = canonical.lower()

    def list_commands(self) -> Dict[str, str]:
        # returns canonical->"has_aliases?" or any metadata you like later
        return dict(self._cmds)

    def call(self, token: str, arg: str = "") -> bool:
        token = (token or "").strip().lower()
        token = self._alias.get(token, token)
        fn = self._cmds.get(token)
        if not fn:
            if token:
                self._bus.push("SYSTEM/WARN", f"Unknown command: {token}")
            return False
        fn(arg)
        return True
