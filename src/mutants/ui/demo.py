"""Tiny demo for the room renderer."""
from __future__ import annotations

from . import renderer

EX_A = {
    "header": "Broken glass covers the road.",
    "coords": {"x": -1, "y": -2},
    "dirs": {
        "N": {"base": 0},
        "S": {"base": 0},
        "E": {"base": 3, "gate_state": 0, "key_type": None},
        "W": {"base": 0},
    },
    "monsters_here": [],
    "ground_item_ids": ["broken_weapon"],
    "has_ground": True,
    "events": [],
    "shadows": ["E", "S"],
}

EX_B = {
    "header": "The market square is littered with debris.",
    "coords": {"x": 3, "y": 0},
    "dirs": {
        "N": {"base": 1},
        "S": {"base": 0},
        "E": {"base": 3, "gate_state": 1},
        "W": {"base": 2},
    },
    "monsters_here": [{"name": "Ghoul"}, {"name": "Sasquatch-331"}],
    "ground_item_ids": [
        "gold_chunk",
        "bottle_cap",
        "cigarette_butt",
        "cheese",
        "ion_decay",
        "nuclear_waste",
        "light_spear",
        "monster_bait",
    ],
    "has_ground": True,
    "events": [
        "The Ghoul hisses.",
        "Sasquatch-331 tightens its grip.",
    ],
    "shadows": [],
}

EX_C = {
    "header": "A cold draft flows through the alley.",
    "coords": {"x": 0, "y": 5},
    "dirs": {
        "N": {"base": 0},
        "S": {"base": 3, "gate_state": 2, "key_type": 4},
        "E": {"base": 0},
        "W": {"base": 0},
    },
    "monsters_here": [],
    "ground_item_ids": [],
    "has_ground": False,
    "events": [],
    "shadows": ["W"],
    "flags": {"dark": True},
}


def main() -> None:
    for vm in (EX_A, EX_B, EX_C):
        for line in renderer.token_debug_lines(vm):
            print(line)
        print()


if __name__ == "__main__":
    main()
