from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

from mutants.state import state_path


class LogSink:
    """Ring buffer sink that also appends to a file."""

    def __init__(self, capacity: int = 200, file_path: str | Path | None = state_path("logs", "game.log")) -> None:
        self.capacity = capacity
        self.file_path = Path(file_path) if file_path else None
        self.buffer: List[str] = []
        if self.file_path:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, kind: str, text: str, ts: str) -> None:
        """Preferred API: add a log event with explicit fields."""
        line = f"{ts} {kind} - {text}"
        self.buffer.append(line)
        if len(self.buffer) > self.capacity:
            self.buffer = self.buffer[-self.capacity :]
        if self.file_path:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

    def handle(self, ev: Dict[str, str]) -> None:
        """Legacy shim: accept dicts as used by some commands."""
        self.add(ev.get("kind", ""), ev.get("text", ""), ev.get("ts", ""))

    def tail(self, n: int = 100) -> List[str]:
        return self.buffer[-n:]

    def clear(self) -> None:
        self.buffer.clear()
