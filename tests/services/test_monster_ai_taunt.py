from __future__ import annotations

import random
from typing import List, Tuple

from mutants.services.monster_ai import taunt


class DummyBus:
    def __init__(self) -> None:
        self.events: List[Tuple[str, str]] = []

    def push(self, kind: str, text: str) -> None:
        self.events.append((kind, text))


def test_emit_taunt_probability_with_seed() -> None:
    monster = {"name": "Goblin", "taunt": "Grr!"}
    bus = DummyBus()
    rng = random.Random(0)

    ready_count = 0
    for _ in range(1000):
        outcome = taunt.emit_taunt(monster, bus, rng)
        if outcome["ready"]:
            ready_count += 1

    assert ready_count == 53
    ready_events = [ev for ev in bus.events if ev[0] == "COMBAT/READY"]
    assert len(ready_events) == ready_count
    assert all(ev[1] == "Goblin is getting ready to combat you!" for ev in ready_events)


def test_emit_taunt_skips_without_line() -> None:
    monster = {"name": "Goblin", "taunt": "   "}
    bus = DummyBus()
    rng = random.Random(1)

    outcome = taunt.emit_taunt(monster, bus, rng)

    assert outcome == {"ok": True, "message": None, "ready": False, "ready_message": None}
    assert bus.events == []
