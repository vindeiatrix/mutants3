import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mutants.ui import renderer

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


class RendererExamplesTest(unittest.TestCase):
    def test_example_a(self) -> None:
        lines = renderer.token_debug_lines(EX_A)
        expected = [
            "<HEADER>Broken glass covers the road.</HEADER>",
            "<COMPASS_LABEL>Compass:</COMPASS_LABEL> <COORDS>(-1E : -2N)</COORDS>",
            "<DIR>north</DIR>  - <DESC_CONT>area continues.</DESC_CONT>",
            "<DIR>south</DIR>  - <DESC_CONT>area continues.</DESC_CONT>",
            "<DIR>east</DIR>  - <DESC_GATE_OPEN>open gate.</DESC_GATE_OPEN>",
            "<DIR>west</DIR>  - <DESC_CONT>area continues.</DESC_CONT>",
            "***",
            "<LABEL>On the ground lies:</LABEL>",
            "<ITEM>A Broken‑Weapon.</ITEM>",
            "<SHADOWS_LABEL>You see shadows to the east, south.</SHADOWS_LABEL>",
        ]
        self.assertEqual(lines, expected)

    def test_example_b(self) -> None:
        lines = renderer.token_debug_lines(EX_B)
        expected = [
            "<HEADER>The market square is littered with debris.</HEADER>",
            "<COMPASS_LABEL>Compass:</COMPASS_LABEL> <COORDS>(3E : 0N)</COORDS>",
            "<DIR>south</DIR>  - <DESC_CONT>area continues.</DESC_CONT>",
            "<DIR>east</DIR>  - <DESC_GATE_CLOSED>closed gate.</DESC_GATE_CLOSED>",
            "***",
            "<MONSTER>Ghoul is here.</MONSTER>",
            "<MONSTER>Sasquatch-331 is here.</MONSTER>",
            "<LABEL>On the ground lies:</LABEL>",
            "<ITEM>A Gold‑Chunk, A Bottle‑Cap, A Cigarette‑Butt, A Cheese, An Ion‑Decay,</ITEM>",
            "<ITEM>A Nuclear‑Waste, A Light‑Spear, A Monster‑Bait.</ITEM>",
            "The Ghoul hisses.",
            "Sasquatch-331 tightens its grip.",
        ]
        self.assertEqual(lines, expected)

    def test_example_c(self) -> None:
        lines = renderer.token_debug_lines(EX_C)
        expected = [
            "<HEADER>A cold draft flows through the alley.</HEADER>",
            "<COMPASS_LABEL>Compass:</COMPASS_LABEL> <COORDS>(0E : 5N)</COORDS>",
            "<DIR>north</DIR>  - <DESC_CONT>area continues.</DESC_CONT>",
            "<DIR>south</DIR>  - <DESC_GATE_LOCKED>locked gate.</DESC_GATE_LOCKED>",
            "<DIR>east</DIR>  - <DESC_CONT>area continues.</DESC_CONT>",
            "<DIR>west</DIR>  - <DESC_CONT>area continues.</DESC_CONT>",
            "***",
            "<SHADOWS_LABEL>You see shadows to the west.</SHADOWS_LABEL>",
        ]
        self.assertEqual(lines, expected)


if __name__ == "__main__":  # pragma: no cover - unittest main
    unittest.main()
