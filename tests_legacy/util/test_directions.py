from mutants.util.directions import resolve_dir


def test_all_prefixes_resolve():
    assert resolve_dir("n") == "north"
    assert resolve_dir("no") == "north"
    assert resolve_dir("nor") == "north"
    assert resolve_dir("nort") == "north"
    assert resolve_dir("north") == "north"
    assert resolve_dir("s") == "south"
    assert resolve_dir("so") == "south"
    assert resolve_dir("sou") == "south"
    assert resolve_dir("sout") == "south"
    assert resolve_dir("south") == "south"
    assert resolve_dir("e") == "east"
    assert resolve_dir("ea") == "east"
    assert resolve_dir("eas") == "east"
    assert resolve_dir("east") == "east"
    assert resolve_dir("w") == "west"
    assert resolve_dir("we") == "west"
    assert resolve_dir("wes") == "west"
    assert resolve_dir("west") == "west"


def test_invalid_returns_none():
    assert resolve_dir("") is None
    assert resolve_dir("northwest") is None
    assert resolve_dir("x") is None
