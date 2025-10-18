from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.generate_combat_log import generate_combat_log


_GOLDEN_SEED = 20240517
_GOLDEN_TURNS = 10


def test_combat_log_matches_golden_snapshot() -> None:
    golden_path = Path(__file__).with_name("combat_log.txt")
    expected = golden_path.read_text(encoding="utf-8")
    actual = generate_combat_log(seed=_GOLDEN_SEED, turns=_GOLDEN_TURNS)
    assert actual == expected
