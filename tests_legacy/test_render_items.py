from mutants.ui.render_items import harden_display_nonbreak


def test_display_name_uses_non_breaking_chars():
    s = "A Nuclear-Decay"
    hardened = harden_display_nonbreak(s)
    assert "-" not in hardened
    assert "\u2011" in hardened
    assert "\u00A0" in hardened

