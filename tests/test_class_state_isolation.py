from __future__ import annotations

import contextlib
import importlib
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mutants.services import player_state


def _reload_state_modules() -> None:
    import mutants.state as state_mod
    import mutants.env as env_mod

    importlib.reload(state_mod)
    importlib.reload(env_mod)


def _build_command_runner():
    from mutants.app.context import build_context, flush_feedback, render_frame
    from mutants.commands.register_all import register_all
    from mutants.repl.dispatch import Dispatch

    ctx = build_context()
    ctx["mode"] = "play"
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])
    dispatch.set_context(ctx)
    register_all(dispatch, ctx)

    def run(cmd: str) -> str:
        token, _, arg = cmd.strip().partition(" ")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            dispatch.call(token, arg)
            if ctx.get("render_next"):
                render_frame(ctx)
                ctx["render_next"] = False
            else:
                flush_feedback(ctx)
        return buffer.getvalue()

    return ctx, run


def _normalize(text: str) -> str:
    normalized = text.lower().replace("\u00a0", " ")
    for hyphen in ["\u2011", "\u2013", "\u2014", "\u2212"]:
        normalized = normalized.replace(hyphen, "-")
    return normalized


def _active_id(state: dict, class_name: str) -> str:
    for entry in state.get("players", []):
        if entry.get("class") == class_name:
            return entry["id"]
    raise ValueError(f"class not found: {class_name}")


def _seed_class_defaults(state: dict) -> None:
    from mutants.bootstrap import lazyinit

    templates = {tpl["class"]: tpl for tpl in lazyinit.load_templates()}
    state.setdefault("ready_target_by_class", {})
    state.setdefault("target_monster_id_by_class", {})
    for entry in state.get("players", []):
        cls = entry.get("class")
        template = templates.get(cls, {})
        player_state.set_active_player(state, entry["id"])
        player_state.save_state(state)
        stats = template.get("base_stats", {})
        player_state.set_stats_for_active(state, stats)
        hp_max = int(template.get("hp_max_start", 0) or 0)
        player_state.set_hp_for_active(state, {"current": hp_max, "max": hp_max})
        player_state.set_exhaustion_for_active(state, int(template.get("exhaustion_start", 0) or 0))
        state["ready_target_by_class"][cls] = None
        state["target_monster_id_by_class"][cls] = None
    player_state.save_state(state)


@pytest.fixture()
def game_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "json")
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("DEBUG", "1")
    _reload_state_modules()

    from mutants.registries import items_catalog, sqlite_store, storage

    items_path = REPO_ROOT / "state" / "items" / "catalog.json"
    db_path = Path(tmp_path) / "mutants.db"
    manager = sqlite_store.SQLiteConnectionManager(db_path)
    manager.connect()
    for item in json.loads(items_path.read_text(encoding="utf-8")):
        manager.upsert_item_catalog(item["item_id"], json.dumps(item))

    stores = sqlite_store.get_stores(db_path)
    monkeypatch.setattr(storage, "get_stores", lambda: stores)
    monkeypatch.setattr(items_catalog, "_CATALOG_CACHE", None)

    base_state = player_state.ensure_class_profiles({})
    seeded = player_state.migrate_per_class_fields(base_state)
    player_state.save_state(seeded)
    _seed_class_defaults(player_state.load_state())
    return tmp_path


def test_resource_and_progression_isolation(game_env: Path):
    state = player_state.load_state()
    thief_id = _active_id(state, "Thief")
    warrior_id = _active_id(state, "Warrior")

    player_state.set_active_player(state, thief_id)
    player_state.save_state(state)

    player_state.set_ions_for_active(state, 5000)
    player_state.set_riblets_for_active(state, 10)
    player_state.set_exp_for_active(state, 1000)
    player_state.set_level_for_active(state, 5)

    state = player_state.load_state()
    player_state.set_active_player(state, warrior_id)
    player_state.save_state(state)

    assert player_state.get_ions_for_active(state) == 30000
    assert player_state.get_riblets_for_active(state) == 0
    assert player_state.get_exp_for_active(state) == 0
    assert player_state.get_level_for_active(state) == 1

    player_state.set_ions_for_active(state, 200)

    state = player_state.load_state()
    player_state.set_active_player(state, thief_id)
    player_state.save_state(state)

    assert player_state.get_ions_for_active(state) == 5000
    assert player_state.get_riblets_for_active(state) == 10
    assert player_state.get_exp_for_active(state) == 1000
    assert player_state.get_level_for_active(state) == 5


def test_vital_and_attribute_isolation(game_env: Path):
    state = player_state.load_state()
    thief_id = _active_id(state, "Thief")
    warrior_id = _active_id(state, "Warrior")

    player_state.set_active_player(state, thief_id)
    player_state.save_state(state)

    player_state.set_stats_for_active(state, {"str": 10, "int": 18})
    player_state.set_hp_for_active(state, {"current": 5, "max": 20})
    player_state.set_exhaustion_for_active(state, 50)

    state = player_state.load_state()
    player_state.set_active_player(state, warrior_id)
    player_state.save_state(state)

    warrior_stats = player_state.get_stats_for_active(state)
    warrior_hp = player_state.get_hp_for_active(state)

    assert warrior_stats.get("str") == 23
    assert warrior_stats.get("dex") == 20
    assert warrior_hp.get("current") == 40
    assert warrior_hp.get("max") == 40
    assert player_state.get_exhaustion_for_active(state) == 0

    state = player_state.load_state()
    player_state.set_active_player(state, thief_id)
    player_state.save_state(state)

    thief_stats = player_state.get_stats_for_active(state)
    thief_hp = player_state.get_hp_for_active(state)

    assert thief_stats.get("str") == 10
    assert thief_stats.get("int") == 18
    assert thief_hp.get("current") == 5
    assert thief_hp.get("max") == 20
    assert player_state.get_exhaustion_for_active(state) == 50


def test_combat_target_resets_on_switch(game_env: Path):
    state = player_state.load_state()
    thief_id = _active_id(state, "Thief")
    warrior_id = _active_id(state, "Warrior")

    player_state.set_active_player(state, thief_id)
    player_state.save_state(state)

    state = player_state.load_state()
    ready_map = state.setdefault("ready_target_by_class", {})
    target_map = state.setdefault("target_monster_id_by_class", {})
    for cls_name in list(ready_map):
        ready_map[cls_name] = None
    for cls_name in list(target_map):
        target_map[cls_name] = None
    ready_map["Thief"] = "rat"
    target_map["Thief"] = "rat"
    ready_map.setdefault("Warrior", None)
    target_map.setdefault("Warrior", None)
    player_state.save_state(state)

    assert player_state.get_ready_target_for_active(player_state.load_state()) == "rat"

    state = player_state.load_state()
    player_state.set_active_player(state, warrior_id)
    player_state.save_state(state)
    player_state.clear_ready_target_for_active(reason="class-switch")

    assert player_state.get_ready_target_for_active(player_state.load_state()) is None

    state = player_state.load_state()
    player_state.set_active_player(state, thief_id)
    ready_map = state.get("ready_target_by_class", {})
    ready_map["Thief"] = None
    target_map = state.get("target_monster_id_by_class", {})
    target_map["Thief"] = None
    active = state.get("active", {})
    active["ready_target"] = None
    active["target_monster_id"] = None
    player_state.save_state(state)

    assert player_state.get_ready_target_for_active(player_state.load_state()) is None


def test_equipment_and_ac_isolation(game_env: Path):
    state = player_state.load_state()
    thief_id = _active_id(state, "Thief")
    warrior_id = _active_id(state, "Warrior")

    equipment_map = state.setdefault("equipment_by_class", {})
    armour_state = state.setdefault("armour", {})
    equipment_map["Thief"] = {"armour": "scrap_armour"}
    armour_state["wearing"] = "scrap_armour"
    player_state.set_active_player(state, thief_id)
    player_state.save_state(state)

    state = player_state.load_state()
    player_state.set_active_player(state, warrior_id)
    equipment_map = state.setdefault("equipment_by_class", {})
    armour_state = state.setdefault("armour", {})
    equipment_map["Warrior"] = {"armour": None}
    armour_state["wearing"] = None
    player_state.save_state(state)

    warrior_equipped = player_state.get_equipped_armour_id(player_state.load_state())
    assert warrior_equipped is None

    state = player_state.load_state()
    equipment_map = state.setdefault("equipment_by_class", {})
    equipment_map["Warrior"] = {"armour": "plate_mail"}
    player_state.save_state(state)

    state = player_state.load_state()
    player_state.set_active_player(state, thief_id)
    player_state.save_state(state)

    thief_equipped = player_state.get_equipped_armour_id(player_state.load_state())
    assert thief_equipped == "scrap_armour"


def test_full_statistics_page_rendering(game_env: Path):
    state = player_state.load_state()
    thief_id = _active_id(state, "Thief")
    mage_id = _active_id(state, "Mage")

    player_state.set_active_player(state, thief_id)
    player_state.save_state(state)

    player_state.set_stats_for_active(state, {"str": 7, "int": 15})
    player_state.set_hp_for_active(state, {"current": 12, "max": 21})
    player_state.set_exhaustion_for_active(state, 5)
    player_state.set_exp_for_active(state, 777)
    player_state.set_level_for_active(state, 4)
    player_state.set_ions_for_active(state, 11111)
    player_state.set_riblets_for_active(state, 33)

    ctx, run = _build_command_runner()
    thief_stat = _normalize(run("stat"))
    assert "mutant thief" in thief_stat
    assert "str:   7" in thief_stat
    assert "int:  15" in thief_stat
    assert "hit points  : 12 / 21" in thief_stat
    assert "exp. points : 777" in thief_stat
    assert "level: 4" in thief_stat
    assert "riblets     : 33" in thief_stat
    assert "ions        : 11111" in thief_stat

    state = player_state.load_state()
    player_state.set_active_player(state, mage_id)
    player_state.save_state(state)

    ctx, run = _build_command_runner()
    mage_stat = _normalize(run("stat"))
    assert "mutant mage" in mage_stat
    assert "ions        : 30000" in mage_stat
    assert "riblets     : 0" in mage_stat
    assert "exp. points : 0" in mage_stat
    assert "level: 1" in mage_stat
    assert "wearing armor : none" in mage_stat
    assert "hit points  : 28 / 28" in mage_stat
    assert "str:  18" in mage_stat
    assert "int:  23" in mage_stat
