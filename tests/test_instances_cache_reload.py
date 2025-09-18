from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from src.mutants.registries import items_instances as itemsreg


def _copy_state(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)


def test_cache_refreshes_when_timestamp_moves_backwards(monkeypatch, tmp_path):
    src_state = Path(__file__).resolve().parents[1] / "state"
    dst_state = tmp_path / "state"
    _copy_state(src_state, dst_state)

    monkeypatch.chdir(tmp_path)
    itemsreg.invalidate_cache()

    iid = itemsreg.create_and_save_instance("skull", 2000, 0, 0)
    cached = itemsreg.list_instances_at(2000, 0, 0)
    assert any((inst.get("iid") or inst.get("instance_id")) == iid for inst in cached)

    path = Path("state/items/instances.json")
    before_mtime = path.stat().st_mtime

    with path.open("w", encoding="utf-8") as f:
        json.dump([], f)

    older = before_mtime - 10 if before_mtime else 0
    os.utime(path, (older, older))

    refreshed = itemsreg.list_instances_at(2000, 0, 0)
    try:
        assert refreshed == []
    finally:
        itemsreg.invalidate_cache()
