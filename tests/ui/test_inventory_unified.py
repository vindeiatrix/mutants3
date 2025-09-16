from __future__ import annotations

from typing import Any, Dict, List

from mutants.commands import inv, statistics
from mutants.ui.inventory_final import render_inventory_final


class FakeItems:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {
            "ion_pack": {"name": "Ion Pack", "weight_lb": 3},
            "med_kit": {"name": "Med Kit", "weight_lb": 2},
            "mystery_box": {"name": "Mystery Box", "weight_lb": 0},
        }

    def get_display_name(self, iid: str) -> Dict[str, Any]:
        return dict(self._data.get(iid, {"name": f"Item {iid}"}))

    def get_weight_lb(self, iid: str) -> int:
        info = self._data.get(iid)
        if info is None:
            return 0
        return int(info.get("weight_lb", 0))


class FakePlayer:
    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    def to_dict(self) -> Dict[str, Any]:
        return self._data


class FakeStateManager:
    def __init__(self, player: Dict[str, Any]) -> None:
        self._player = player

    def get_active(self) -> FakePlayer:
        return FakePlayer(self._player)


class FakeBus:
    def __init__(self) -> None:
        self.events: List[tuple[str, str]] = []

    def push(self, kind: str, text: str, **_meta: Any) -> None:
        self.events.append((kind, text))


def _inventory_section(events: List[tuple[str, str]]) -> List[str]:
    texts = [text for _, text in events]
    for idx, text in enumerate(texts):
        if text.startswith("You are carrying the following items:"):
            return texts[idx:]
    return []


def test_render_inventory_empty() -> None:
    lines, total = render_inventory_final({"inventory": []}, FakeItems())
    assert lines == ["Nothing."]
    assert total == 0


def test_inventory_command_matches_statistics_inventory() -> None:
    player = {
        "name": "Test Subject",
        "class": "Wizard",
        "hp": {"current": 5, "max": 10},
        "stats": {"str": 3, "int": 9, "wis": 4, "dex": 5, "con": 6, "cha": 7},
        "armour": {"armour_class": 1},
        "pos": [2000, 0, 0],
        "riblets": 0,
        "ions": 0,
        "exp_points": 0,
        "exhaustion": 0,
        "level": 1,
        "inventory": ["ion_pack", "med_kit", "mystery_box"],
    }
    items = FakeItems()

    bus_inv = FakeBus()
    ctx_inv = {"feedback_bus": bus_inv, "state_manager": FakeStateManager(player), "items": items}
    inv.inv_cmd("", ctx_inv)
    inventory_output = [text for _, text in bus_inv.events]

    bus_stat = FakeBus()
    ctx_stat = {"feedback_bus": bus_stat, "state_manager": FakeStateManager(player), "items": items}
    statistics.statistics_cmd("", ctx_stat)
    statistics_output = _inventory_section(bus_stat.events)

    assert statistics_output
    assert inventory_output == statistics_output
