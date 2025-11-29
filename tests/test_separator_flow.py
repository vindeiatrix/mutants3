from mutants.app import context
from mutants.ui import uicontract as UC


def test_format_feedback_events_interleaves_separator_lines() -> None:
    events = [
        {"kind": "SYSTEM/OK", "text": "first"},
        {"kind": "SYSTEM/WARN", "text": "second"},
    ]

    lines = context._format_feedback_events(events, palette={})

    assert lines[0] == "first"
    assert lines[1] == UC.SEPARATOR_LINE
    assert lines[2] == "second"
    assert lines[-1] != UC.SEPARATOR_LINE


def test_prepend_leading_separator_adds_single_prefix() -> None:
    lines = ["first", UC.SEPARATOR_LINE, "second"]

    prefixed = context._prepend_leading_separator(lines)

    assert prefixed[0] == UC.SEPARATOR_LINE
    assert prefixed[1:] == lines


def test_prepend_leading_separator_preserves_existing_prefix() -> None:
    lines = [UC.SEPARATOR_LINE, "first", UC.SEPARATOR_LINE, "second"]

    prefixed = context._prepend_leading_separator(lines)

    assert prefixed == lines
