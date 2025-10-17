from __future__ import annotations

from mutants.world import vision


class _FakeMonsters:
    def __init__(self, responses):
        self._responses = list(responses)

    def list_adjacent_monsters(self, player_pos):  # pragma: no cover - signature by contract
        if not self._responses:
            return []
        return self._responses.pop(0)


def test_direction_word_handles_diagonals():
    assert vision.direction_word("NE") == "northeast"
    assert vision.direction_word("southwest") == "southwest"
    assert vision.direction_word("nw") == "northwest"


def test_adjacent_monster_directions_toggle():
    monsters = _FakeMonsters([
        ["N", "se", "NE"],
        [],
    ])
    pos = (2000, 10, 10)

    first = vision.adjacent_monster_directions(monsters, pos)
    assert first == ["NE", "SE", "N"]

    second = vision.adjacent_monster_directions(monsters, pos)
    assert second == []
