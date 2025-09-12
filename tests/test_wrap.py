from mutants.ui.wrap import wrap, wrap_segments, wrap_list


def test_wrap_does_not_break_on_hyphen():
    text = "A Nuclear-Decay, A Bottle-Cap, A Bottle-Cap (1)"
    lines = wrap(text, width=40)
    joined = "\n".join(lines)
    assert "Nuclear-\nDecay" not in joined
    assert "Bottle-\nCap" not in joined


def test_wrap_segments_no_hyphen_break():
    segs = [
        "On the ground lies: ",
        "A Nuclear-Decay, A Bottle-Cap, A Bottle-Cap (1)",
    ]
    lines = wrap_segments(segs, width=40)
    joined = "\n".join(lines)
    assert "Nuclear-\nDecay" not in joined
    assert "Bottle-\nCap" not in joined


def test_wrap_list_no_hyphen_break():
    items = ["A Nuclear-Decay", "A Bottle-Cap", "A Bottle-Cap (1)"]
    lines = wrap_list(items, width=40)
    joined = "\n".join(lines)
    assert "Nuclear-\nDecay" not in joined
    assert "Bottle-\nCap" not in joined

