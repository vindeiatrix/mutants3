from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.services import monsters_state  # noqa: E402


@pytest.fixture(autouse=True)
def patch_items_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monsters_state.items_catalog, "load_catalog", lambda: {})


@pytest.fixture(autouse=True)
def patch_items_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monsters_state.items_weight, "get_effective_weight", lambda *_args, **_kwargs: 0)


def _baseline_stats() -> dict[str, int]:
    return {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0}


def test_auto_equip_armour_swaps_to_highest_class() -> None:
    monster = {
        "stats": _baseline_stats(),
        "bag": [
            {"iid": "armour_new", "derived": {"armour_class": 6}},
        ],
        "armour_slot": {"iid": "armour_old", "derived": {"armour_class": 3}},
    }

    monsters_state._refresh_monster_derived(monster)

    assert monster["armour_slot"]["iid"] == "armour_new"
    assert any(entry["iid"] == "armour_old" for entry in monster["bag"])


def test_auto_equip_melee_upgrade_wields_immediately() -> None:
    monster = {
        "stats": _baseline_stats(),
        "bag": [
            {"iid": "sword_old", "derived": {"base_damage": 4, "is_ranged": False}},
            {"iid": "sword_new", "derived": {"base_damage": 7, "is_ranged": False}},
        ],
        "wielded": "sword_old",
    }

    monsters_state._refresh_monster_derived(monster)

    assert monster["wielded"] == "sword_new"


def test_auto_equip_respects_prefers_ranged_hint() -> None:
    monster = {
        "stats": _baseline_stats(),
        "bag": [
            {"iid": "bolt_staff", "derived": {"base_damage": 5, "is_ranged": True}},
            {"iid": "axe_prime", "derived": {"base_damage": 8, "is_ranged": False}},
        ],
        "wielded": "bolt_staff",
        "prefers_ranged": True,
    }

    monsters_state._refresh_monster_derived(monster)

    assert monster["wielded"] == "bolt_staff"
