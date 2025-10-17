from __future__ import annotations

from mutants.ui import renderer, uicontract as UC


def _base_vm() -> dict:
    return {
        "header": "Test Room",
        "coords": {"x": 0, "y": 0},
        "dirs": {},
        "monsters_here": [],
        "ground_item_ids": [],
        "has_ground": False,
        "events": [],
        "shadows": [],
    }


def _extract_text(lines):
    return ["".join(text for _, text in segments) for segments in lines]


def test_cues_rendered_with_separators() -> None:
    vm = _base_vm()
    vm["cues_lines"] = [
        "You hear footsteps far to the west.",
        "You hear yelling to the east.",
    ]

    lines = renderer.render_token_lines(vm)
    texts = _extract_text(lines)

    first = vm["cues_lines"][0]
    second = vm["cues_lines"][1]

    first_idx = texts.index(first)
    second_idx = texts.index(second)

    assert first_idx > 0
    assert texts[first_idx - 1] == UC.SEPARATOR_LINE
    assert second_idx == first_idx + 2
    assert texts[first_idx + 1] == UC.SEPARATOR_LINE
