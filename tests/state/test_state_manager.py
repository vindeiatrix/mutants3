from __future__ import annotations

import json
from pathlib import Path

from mutants.state.manager import StateManager


TEMPLATE_SRC = Path("state/playerlivestate.json")


def _copy_template(tmp_path) -> Path:
    data = json.loads(TEMPLATE_SRC.read_text(encoding="utf-8"))
    tpl_path = tmp_path / "template.json"
    tpl_path.write_text(json.dumps(data), encoding="utf-8")
    return tpl_path


def test_load_template_reads_known_classes(tmp_path):
    tpl_path = _copy_template(tmp_path)
    templates = StateManager.load_template(tpl_path)
    assert set(templates.keys()) == {
        "player_thief",
        "player_priest",
        "player_wizard",
        "player_warrior",
        "player_mage",
    }


def test_state_manager_initializes_save(tmp_path, monkeypatch):
    tpl_path = _copy_template(tmp_path)
    save_path = tmp_path / "save.json"

    calls: list[Path] = []

    def fake_atomic(path, payload):
        calls.append(Path(path))

    monkeypatch.setattr("mutants.state.manager.atomic_write_json", fake_atomic)

    mgr = StateManager(template_path=tpl_path, save_path=save_path)
    # First persist happens during initialization.
    assert calls, "expected save to be written during initialization"
    calls.clear()

    assert mgr.active_id == "player_thief"
    mgr.switch_active("player_priest")
    assert mgr.active_id == "player_priest"
    assert calls, "expected save on class switch"


def test_switch_active_updates_legacy_view(tmp_path, monkeypatch):
    tpl_path = _copy_template(tmp_path)
    save_path = tmp_path / "save.json"

    monkeypatch.setattr("mutants.state.manager.atomic_write_json", lambda p, d: None)

    mgr = StateManager(template_path=tpl_path, save_path=save_path)
    legacy = mgr.legacy_state
    assert legacy["active_id"] == "player_thief"
    mgr.switch_active("player_wizard")
    assert legacy["active_id"] == "player_wizard"
