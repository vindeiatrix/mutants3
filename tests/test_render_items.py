from mutants.ui.render_items import _no_break_hyphens


def test_display_name_uses_no_break_hyphen():
    s = "A Nuclear-Decay"
    hardened = _no_break_hyphens(s)
    assert "-" not in hardened
    assert "\u2011" in hardened

