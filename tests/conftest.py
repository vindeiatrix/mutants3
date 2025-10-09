from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mutants.registries import sqlite_store
from mutants.services import monsters_state


@pytest.fixture
def monsters_store(tmp_path: Path, monkeypatch) -> Any:
    db_path = tmp_path / "monsters.db"
    stores = sqlite_store.get_stores(db_path)
    store = stores.monsters
    store.replace_all([])
    store_ref = store

    def _loader(
        path: Path | str = monsters_state.DEFAULT_MONSTERS_PATH,
        *,
        store: Any | None = None,
    ) -> monsters_state.monsters_instances.MonstersInstances:
        active_store = store or store_ref
        return monsters_state.monsters_instances.MonstersInstances(path, [], store=active_store)
    monkeypatch.setattr(monsters_state.monsters_instances, "load_monsters_instances", _loader)
    return store
