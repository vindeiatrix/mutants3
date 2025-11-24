from __future__ import annotations

import contextlib
import importlib
import io
import os
import re
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


GAMEPLAY_LOG = dedent(
    """
    Gameplay evidence (manual repro):

    debug add scrap
    get sc
    wear sc
    rem
    drop sc
    You drop the Scrap-Armour
    stat
    > Scrap-Armour still listed in inventory; not on ground.
    """
)


def _reload_state_modules() -> None:
    """Force state/env modules to re-read GAME_STATE_ROOT."""
    import mutants.state as state_mod
    import mutants.env as env_mod

    importlib.reload(state_mod)
    importlib.reload(env_mod)


def _run_admin_command(args: list[str], env: dict[str, str]) -> None:
    subprocess.check_call([sys.executable, "tools/sqlite_admin.py", *args], env=env)


def _import_monsters_catalog(db_path: Path, env: dict[str, str]) -> None:
    catalog_path = Path("state/monsters/catalog.json").resolve()
    subprocess.check_call(
        [
            sys.executable,
            "scripts/monsters_import.py",
            "--catalog",
            str(catalog_path),
            "--db",
            str(db_path),
        ],
        env=env,
    )


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


def test_drop_after_remove_leaves_inventory_incorrectly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reproduce Scrap-Armour drop bug via real command loop."""

    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("DEBUG", "1")

    _reload_state_modules()

    from mutants.env import get_state_database_path

    db_path = get_state_database_path()

    env = os.environ.copy()
    env.update(
        {
            "MUTANTS_STATE_BACKEND": "sqlite",
            "GAME_STATE_ROOT": str(tmp_path),
            "DEBUG": "1",
        }
    )

    _run_admin_command(["init"], env)
    _run_admin_command(["catalog-import-items"], env)
    _import_monsters_catalog(db_path, env)

    ctx, run = _build_command_runner()

    run("debug add scrap")
    run("get sc")
    run("wear sc")
    run("rem")
    run("drop sc")
    stat_output = run("stat")
    look_output = run("look")

    normalized_stat = _normalize(stat_output)
    normalized_look = _normalize(look_output)

    assert "scrap-armour" not in normalized_stat and "scrap armour" not in normalized_stat, (
        "armour should be removed from inventory after drop"
    )
    assert "scrap-armour" in normalized_look or "scrap armour" in normalized_look, (
        "armour should appear on the ground after drop"
    )


def test_throw_item_appears_in_target_room(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ensure thrown items show up in the destination room."""

    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("DEBUG", "1")

    _reload_state_modules()

    env = os.environ.copy()
    env.update(
        {
            "MUTANTS_STATE_BACKEND": "sqlite",
            "GAME_STATE_ROOT": str(tmp_path),
            "DEBUG": "1",
        }
    )

    _run_admin_command(["init"], env)
    _run_admin_command(["catalog-import-items"], env)

    ctx, run = _build_command_runner()

    run("debug add light-spear")
    run("get light-spear")
    run("throw east light-spear")
    run("east")
    look_output = run("look")

    normalized_look = _normalize(look_output)

    assert "light-spear" in normalized_look, "thrown item should appear in the target room after landing"


def test_drop_on_full_ground_swaps_and_remains_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Dropping onto a full ground should swap items and leave the drop visible."""

    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("DEBUG", "1")

    _reload_state_modules()

    env = os.environ.copy()
    env.update(
        {
            "MUTANTS_STATE_BACKEND": "sqlite",
            "GAME_STATE_ROOT": str(tmp_path),
            "DEBUG": "1",
        }
    )

    _run_admin_command(["init"], env)
    _run_admin_command(["catalog-import-items"], env)

    ctx, run = _build_command_runner()

    for _ in range(6):
        run("debug add ion_decay")

    look_output = _normalize(run("look"))
    assert look_output.count("ion-decay") >= 6, "ground should start at capacity"

    run("debug add nuclear_decay")
    run("get nuclear_decay")

    run("drop nuclear_decay")

    normalized_look = _normalize(run("look"))
    normalized_inv = _normalize(run("inv"))

    assert "nuclear-decay" in normalized_look, "dropped item should remain visible on the ground"
    assert "ion-decay" in normalized_inv, "an existing ground item should have been swapped into inventory"


def test_convert_consumes_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Converting an item should pay the player and remove the item from play."""

    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("DEBUG", "1")

    _reload_state_modules()

    env = os.environ.copy()
    env.update(
        {
            "MUTANTS_STATE_BACKEND": "sqlite",
            "GAME_STATE_ROOT": str(tmp_path),
            "DEBUG": "1",
        }
    )

    _run_admin_command(["init"], env)
    _run_admin_command(["catalog-import-items"], env)

    ctx, run = _build_command_runner()

    run("debug add bottle_cap")
    run("get b")

    stat_output = run("stat")
    initial_match = re.search(r"Ions\s*:\s*(\d+)", stat_output)
    assert initial_match, "stat output should include current ion count"
    initial_ions = int(initial_match.group(1))

    convert_output = run("convert b")
    value_match = re.search(r"into\s+(\d+)\s+ions", convert_output, re.IGNORECASE)
    assert value_match, "convert output should include payout amount"
    item_value = int(value_match.group(1))

    final_stat_output = run("stat")
    final_match = re.search(r"Ions\s*:\s*(\d+)", final_stat_output)
    assert final_match, "stat output should include updated ion count"
    final_ions = int(final_match.group(1))

    assert final_ions == initial_ions + item_value, "player should receive ions for converted item"

    normalized_inv = _normalize(run("inv"))
    normalized_look = _normalize(run("look"))

    assert "bottle-cap" not in normalized_inv and "bottle cap" not in normalized_inv, (
        "converted item should be removed from inventory"
    )
    assert "bottle-cap" not in normalized_look and "bottle cap" not in normalized_look, (
        "converted item should not remain on the ground"
    )


def test_travel_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Dropped items should stay in the original room when the player moves."""

    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("DEBUG", "1")

    _reload_state_modules()

    env = os.environ.copy()
    env.update(
        {
            "MUTANTS_STATE_BACKEND": "sqlite",
            "GAME_STATE_ROOT": str(tmp_path),
            "DEBUG": "1",
        }
    )

    _run_admin_command(["init"], env)
    _run_admin_command(["catalog-import-items"], env)

    ctx, run = _build_command_runner()

    run("debug add light-spear")
    run("get light-spear")
    run("drop light-spear")

    starting_look = _normalize(run("look"))
    assert "light-spear" in starting_look, "dropped item should appear in the starting room"

    run("w")
    west_look = _normalize(run("look"))
    assert "light-spear" not in west_look, "dropped item should remain in the starting room"

    run("e")
    east_look = _normalize(run("look"))
    assert "light-spear" in east_look, "dropped item should persist in its original room"


def test_wear_updates_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Equipping and removing armour should update status and inventory indicators."""

    monkeypatch.setenv("MUTANTS_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("DEBUG", "1")

    _reload_state_modules()

    env = os.environ.copy()
    env.update(
        {
            "MUTANTS_STATE_BACKEND": "sqlite",
            "GAME_STATE_ROOT": str(tmp_path),
            "DEBUG": "1",
        }
    )

    _run_admin_command(["init"], env)
    _run_admin_command(["catalog-import-items"], env)

    ctx, run = _build_command_runner()

    run("debug add scrap")
    run("get sc")

    initial_stat = _normalize(run("stat"))
    assert "wearing armor : none" in initial_stat, "player should start with no armour equipped"
    initial_inv = _normalize(run("inv"))
    assert "scrap-armour" in initial_inv, "armour should begin in inventory before being worn"

    run("wear sc")

    equipped_stat = _normalize(run("stat"))
    assert "wearing armor : scrap-armour" in equipped_stat, "armour should be marked as equipped in status"

    equipped_inv = _normalize(run("inv"))
    assert "scrap-armour" not in equipped_inv, "equipped armour should no longer appear in inventory listings"

    run("rem")

    final_stat = _normalize(run("stat"))
    assert "wearing armor : none" in final_stat, "removing armour should clear equipped status"
    final_inv = _normalize(run("inv"))
    assert "scrap-armour" in final_inv, "removed armour should return to inventory"
