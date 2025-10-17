from __future__ import annotations

from mutants.ui import renderer


def _base_vm(shadows):
    return {
        "header": "Test",
        "coords": {"x": 0, "y": 0},
        "dirs": {},
        "monsters_here": [],
        "ground_item_ids": [],
        "has_ground": False,
        "events": [],
        "shadows": list(shadows),
    }


def _extract_text(lines):
    texts = []
    for segments in lines:
        texts.append("".join(text for _, text in segments))
    return texts


def test_shadow_line_includes_diagonal_names():
    vm = _base_vm(["NE", "S"])
    lines = renderer.render_token_lines(vm)
    texts = _extract_text(lines)
    assert "You see shadows to the northeast, south." in texts


def test_shadow_line_omitted_when_no_directions():
    vm = _base_vm([])
    lines = renderer.render_token_lines(vm)
    texts = _extract_text(lines)
    assert all("You see shadows" not in text for text in texts)
