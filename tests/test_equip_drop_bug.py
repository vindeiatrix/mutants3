from __future__ import annotations

import contextlib
import importlib
import io
import os
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

    normalized_stat = stat_output.lower().replace("\u2011", "-")

    assert "scrap-armour" not in normalized_stat and "scrap armour" not in normalized_stat
