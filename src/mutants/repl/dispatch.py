from __future__ import annotations

from typing import Callable, Dict

from mutants.ui.feedback import FeedbackBus


class Dispatch:
    def __init__(self, bus: FeedbackBus) -> None:
        self._cmds: Dict[str, Callable[[str], None]] = {}
        self._aliases: Dict[str, str] = {}
        self.bus = bus

    def register(self, name: str, fn: Callable[[str], None]) -> None:
        self._cmds[name] = fn

    def alias(self, alias_name: str, canonical: str) -> None:
        self._aliases[alias_name] = canonical

    def call(self, token: str, arg: str) -> bool:
        name = self._aliases.get(token, token)
        fn = self._cmds.get(name)
        if fn:
            fn(arg)
            return True
        self.bus.push("SYSTEM/WARN", f"Unknown command: {token}")
        return False
