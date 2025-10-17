from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.services import audio_cues


def test_emit_sound_formats_direction_and_distance() -> None:
    ctx: dict[str, object] = {}

    message = audio_cues.emit_sound((2000, 1, 0), (2000, 0, 0), "yelling", ctx=ctx)

    assert message == "You hear yelling to the east."
    assert audio_cues.drain(ctx) == [message]


def test_emit_sound_marks_far_for_distant_steps() -> None:
    ctx: dict[str, object] = {}

    message = audio_cues.emit_sound((2000, -3, -2), (2000, 0, 0), "footsteps", ctx=ctx)

    assert message == "You hear footsteps far to the southwest."
    assert audio_cues.drain(ctx) == [message]


def test_emit_sound_ignored_when_out_of_range() -> None:
    ctx: dict[str, object] = {}

    message = audio_cues.emit_sound((2000, 6, 0), (2000, 0, 0), "yelling", ctx=ctx)

    assert message is None
    assert audio_cues.drain(ctx) == []


def test_drain_clears_queue() -> None:
    ctx: dict[str, object] = {}

    message = audio_cues.emit_sound((2000, 1, 0), (2000, 0, 0), "footsteps", ctx=ctx)
    first = audio_cues.drain(ctx)
    second = audio_cues.drain(ctx)

    assert first == [message]
    assert second == []
