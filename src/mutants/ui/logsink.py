from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List


class LogSink:
    """Ring buffer sink that also appends to a file."""

    def __init__(self, capacity: int = 200, file_path: str | Path | None = "state/logs/game.log") -> None:
        self.capacity = capacity
        self.file_path = Path(file_path) if file_path else None
        self.buffer: List[str] = []
        if self.file_path:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def handle(self, event: Dict[str, str]) -> None:
        line = f"{event.get('ts', '')} {event.get('kind', '')} - {event.get('text', '')}"
        self.buffer.append(line)
        if len(self.buffer) > self.capacity:
            self.buffer = self.buffer[-self.capacity :]
        if self.file_path:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

    def tail(self, n: int = 50) -> List[str]:
        return self.buffer[-n:]

    def clear(self) -> None:
        self.buffer.clear()
