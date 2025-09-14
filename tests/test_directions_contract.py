from mutants.util import directions as D


def test_delta_and_opposites():
    assert D.vec("north") == (0, 1)
    assert D.vec("south") == (0, -1)
    assert D.vec("east") == (1, 0)
    assert D.vec("west") == (-1, 0)

    assert D.vec("n") == (0, 1)
    assert D.vec("s") == (0, -1)
    assert D.opposite("n") == "s"
    assert D.opposite("south") == "north"
