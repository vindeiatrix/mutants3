from mutants.util.textnorm import normalize_item_query


def test_normalize_basic():
    assert normalize_item_query("Nuclear-Thong") == "nuclear-thong"
    assert normalize_item_query("  the Nuclear Thong  ") == "nuclear-thong"


def test_normalize_quotes_unicode():
    assert normalize_item_query('"A  Nuclear–Thong"') == "nuclear-thong"
    assert normalize_item_query("‘An  Ion—Decay’") == "ion-decay"


def test_normalize_prefix_preserved():
    assert normalize_item_query("NUCLEAR-TH") == "nuclear-th"


def test_normalize_empty_safe():
    assert normalize_item_query("") == ""
    assert normalize_item_query(None) == ""
