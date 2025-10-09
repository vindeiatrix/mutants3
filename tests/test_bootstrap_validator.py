from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from mutants.bootstrap import runtime, validator
from mutants.registries import items_catalog, items_instances
from mutants.registries.sqlite_store import SQLiteConnectionManager
import mutants.state as state


def _write_catalog(db_path: Path) -> None:
    payload = {
        "item_id": "test_blade",
        "name": "Test Blade",
        "spawnable": False,
        "enchantable": False,
        "ranged": False,
        "base_power_melee": 0,
        "base_power_bolt": 0,
        "poison_melee": False,
        "poison_bolt": False,
    }
    db_path.parent.mkdir(parents=True, exist_ok=True)
    manager = SQLiteConnectionManager(db_path)
    manager.upsert_item_catalog("test_blade", json.dumps(payload))


def _write_instances(path: Path, *, duplicate: bool = True) -> None:
    payload = [
        {
            "iid": "dup" if duplicate else "unique-1",
            "instance_id": "dup" if duplicate else "unique-1",
            "item_id": "test_blade",
        },
        {
            "iid": "dup" if duplicate else "unique-2",
            "instance_id": "dup" if duplicate else "unique-2",
            "item_id": "test_blade",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_paths(monkeypatch: pytest.MonkeyPatch, catalog_db: Path, instances: Path) -> None:
    monkeypatch.setattr(items_catalog, "DEFAULT_CATALOG_PATH", catalog_db)
    monkeypatch.setattr(items_catalog, "FALLBACK_CATALOG_PATH", catalog_db)
    catalog_json = instances.parent / "catalog.json"
    monkeypatch.setattr(items_instances, "DEFAULT_INSTANCES_PATH", instances)
    monkeypatch.setattr(items_instances, "FALLBACK_INSTANCES_PATH", instances)
    monkeypatch.setattr(items_instances, "CATALOG_PATH", catalog_json)

    original_catalog_loader = items_catalog.load_catalog

    def _load_catalog(path: Path | str | None = catalog_db):
        return original_catalog_loader(path)

    monkeypatch.setattr(items_catalog, "load_catalog", _load_catalog)

    original_instances_loader = items_instances.load_instances

    def _load_instances(
        path: Path | str = instances, *, strict: bool | None = None
    ) -> list[dict[str, object]]:
        return items_instances._load_instances_from_path(Path(path), strict=strict)

    monkeypatch.setattr(items_instances, "load_instances", _load_instances)
    items_instances.invalidate_cache()


def test_validator_duplicate_iids_strict_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    catalog_path = tmp_path / "mutants.db"
    instances_path = tmp_path / "items" / "instances.json"
    _write_catalog(catalog_path)
    _write_instances(instances_path, duplicate=True)
    _patch_paths(monkeypatch, catalog_path, instances_path)

    with pytest.raises(ValueError):
        validator.run(strict=True)


def test_validator_duplicate_iids_prod_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    catalog_path = tmp_path / "mutants.db"
    instances_path = tmp_path / "items" / "instances.json"
    _write_catalog(catalog_path)
    _write_instances(instances_path, duplicate=True)
    _patch_paths(monkeypatch, catalog_path, instances_path)

    caplog.set_level("INFO", logger="mutants.itemsdbg")
    summary = validator.run(strict=False)
    assert summary["instances"] == 2
    assert any("DUPLICATE_IIDS_DETECTED" in record.message for record in caplog.records)


def test_ensure_runtime_runs_validator_when_dev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    state_module = importlib.reload(state)
    runtime_module = importlib.reload(runtime)

    called = {}

    def _fake_run_on_boot() -> None:
        called["ran"] = True

    monkeypatch.setattr(runtime_module.validator, "run_on_boot", _fake_run_on_boot)
    monkeypatch.setenv("MUTANTS_DEV", "1")

    try:
        info = runtime_module.ensure_runtime()
        assert called.get("ran") is True
        assert isinstance(info.get("years"), list)
    finally:
        monkeypatch.delenv("MUTANTS_DEV", raising=False)
        monkeypatch.delenv("GAME_STATE_ROOT", raising=False)
        importlib.reload(state_module)
        importlib.reload(runtime_module)
