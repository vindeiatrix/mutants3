from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List


class FeedbackBus:
    """Simple feedback event bus."""

    def __init__(self) -> None:
        self._queue: List[Dict[str, str]] = []
        self._subs: List[Callable[[Dict[str, str]], None]] = []

    def push(self, kind: str, text: str, **meta) -> None:
        event: Dict[str, str] = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "kind": kind,
            "text": text,
        }
        if meta:
            event.update(meta)
        self._queue.append(event)
        for fn in self._subs:
            try:
                fn(event)
            except Exception:
                pass

    def drain(self) -> List[Dict[str, str]]:
        events = list(self._queue)
        self._queue.clear()
        return events

    def subscribe(self, listener: Callable[[Dict[str, str]], None]) -> None:
        self._subs.append(listener)
