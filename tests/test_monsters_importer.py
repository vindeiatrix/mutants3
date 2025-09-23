import io
import json
from pathlib import Path

import pytest

from mutants.services import monsters_state
from mutants.services import monsters_importer


@pytest.fixture(autouse=True)
def _clear_monsters_cache():
    monsters_state.invalidate_cache()
    yield
    monsters_state.invalidate_cache()


def _write_state(path: Path, monsters: list[dict]) -> None:
    payload = {"monsters": monsters}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_import_monsters_dry_run_reports_summary(tmp_path, monkeypatch):
    catalog = {
        "club": {"item_id": "club", "base_power": 3, "weight": 10},
        "cloak": {"item_id": "cloak", "armour": True, "armour_class": 1, "weight": 5},
    }
    monkeypatch.setattr(monsters_state.items_catalog, "load_catalog", lambda: catalog)

    payload = [
        {
            "name": "Bandit",
            "bag": [{"item_id": "club", "enchant_level": 0}],
            "armour_slot": {"item_id": "cloak"},
            "wielded": "club",
            "hp": {"current": 5, "max": 5},
            "stats": {"str": 12, "dex": 9},
            "pinned_years": ["2000"],
        },
        {
            "name": "Broken",
            "hp": {"current": 1, "max": 1},
            "stats": {"str": 5},
            "bag": [],
        },
    ]

    input_path = tmp_path / "monsters.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    state_path = tmp_path / "instances.json"

    report = monsters_importer.run_import(input_path, dry_run=True, state_path=state_path)

    assert report.imported_count == 1
    assert report.rejected_count == 1
    assert report.per_year == {2000: 1}
    assert report.minted_iids >= 1
    assert not state_path.exists()

    rendered = io.StringIO()
    monsters_importer.print_report(report, dry_run=True, out=rendered)
    text = rendered.getvalue()
    assert "Dry-run" in text
    assert "minted" in text
    assert "missing" in text or "no valid" in text


def test_import_monsters_real_run_persists_and_normalizes(tmp_path, monkeypatch):
    catalog = {
        "club": {"item_id": "club", "base_power": 3, "weight": 10},
    }
    monkeypatch.setattr(monsters_state.items_catalog, "load_catalog", lambda: catalog)

    payload = [
        {
            "id": "bandit#1",
            "name": "Bandit",
            "bag": [{"item_id": "club"}],
            "wielded": "missing",
            "hp": {"current": 4, "max": 4},
            "stats": {"str": 11, "dex": 8},
            "pinned_years": [2001],
        }
    ]

    input_path = tmp_path / "monsters.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    state_path = tmp_path / "instances.json"

    report = monsters_importer.run_import(input_path, dry_run=False, state_path=state_path)

    assert state_path.exists()
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    monsters = saved["monsters"]
    assert len(monsters) == 1
    monster = monsters[0]
    assert monster["id"] == "bandit#1"
    bag_iid = monster["bag"][0]["iid"]
    assert bag_iid
    assert monster["wielded"] == bag_iid
    assert report.imported_count == 1
    assert report.minted_iids >= 1
    assert any("wielded cleared" in msg for msg in report.records[0].messages)


def test_import_monsters_rejects_duplicate_id(tmp_path, monkeypatch):
    catalog = {"club": {"item_id": "club", "base_power": 3, "weight": 10}}
    monkeypatch.setattr(monsters_state.items_catalog, "load_catalog", lambda: catalog)

    existing = [
        {
            "id": "bandit#1",
            "name": "Bandit",
            "bag": [],
            "hp": {"current": 5, "max": 5},
            "stats": {"str": 10},
            "pinned_years": [1999],
        }
    ]
    state_path = tmp_path / "instances.json"
    _write_state(state_path, existing)

    payload = [
        {
            "id": "bandit#1",
            "name": "Duplicate",
            "bag": [],
            "hp": {"current": 5, "max": 5},
            "stats": {"str": 10},
            "pinned_years": [2005],
        }
    ]

    input_path = tmp_path / "monsters.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    report = monsters_importer.run_import(input_path, dry_run=True, state_path=state_path)

    assert report.imported_count == 0
    assert report.rejected_count == 1
    assert any("duplicate" in msg for msg in report.records[0].messages)

    saved_after = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(saved_after["monsters"]) == 1
