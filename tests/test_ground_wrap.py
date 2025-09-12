from mutants.ui.wrap import wrap_list
from mutants.ui.textutils import harden_final_display


def test_ground_wrap_no_hyphen_breaks_80():
    base = "A Nuclear-Decay"
    items = [base] + [f"{base} ({i})" for i in range(1, 12)]
    hardened = [harden_final_display(s) for s in items]
    lines = wrap_list(hardened, width=80)
    joined = "\n".join(lines)
    assert "Nuclear-\nDecay" not in joined


def test_article_bound_with_nbsp():
    s = harden_final_display("A Nuclear-Decay")
    assert "\u00A0" in s
    assert "\u2011" in s


def test_inventory_no_hyphen_breaks():
    items = ["A Bottle-Cap", "A Nuclear-Decay (1)"]
    hardened = [harden_final_display(s) for s in items]
    lines = wrap_list(hardened, width=40)
    joined = "\n".join(lines)
    assert "Bottle-\nCap" not in joined
