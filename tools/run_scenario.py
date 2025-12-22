from __future__ import annotations

"""
Lightweight scripted-play runner for the Mutants BBS game.

Usage:
    python tools/run_scenario.py scenarios/kill_block.json

Scenario file (JSON):
{
  "name": "kill_block",
  "commands": [
    "bury all",
    "4",
    "debug hp 999999",
    "debug add nuclear_decay",
    "wield nuclear-decay",
    "debug monster waste_mauler",
    "com waste",
    "att",
    "att",
    "x"
  ],
  "expect": [
    "You have slain",
    "Riblets and",
    "is falling from",
    "is crumbling to dust"
  ],
  "timeout_seconds": 40,
  "stdin_delay_ms": 150
}

Notes:
- The runner streams stdout/stderr to a log file in .tmp/scenario_logs/<name>.log.
- Expectations are simple substring checks in order (each must appear somewhere in the log).
- Commands are written with a small delay between them; adjust stdin_delay_ms if prompts are skipped.
- The game must be able to start from the repo root; the runner uses Run-Mutants.ps1.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from subprocess import Popen, PIPE, STDOUT, run

ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = ROOT / ".tmp" / "scenario_logs"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY_EXE = str(VENV_PY if VENV_PY.exists() else sys.executable)
STATE_DIR = ROOT / "state"
DB_PATH = STATE_DIR / "mutants.db"


def load_scenario(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("scenario must be a JSON object")
    return data


def write_commands(proc: Popen, commands: list[str], delay_ms: int) -> None:
    for cmd in commands:
        if proc.stdin is None:
            break
        proc.stdin.write(cmd + "\n")
        proc.stdin.flush()
        time.sleep(max(0, delay_ms) / 1000.0)


def run_scenario(path: Path) -> int:
    scenario = load_scenario(path)
    name = scenario.get("name") or path.stem
    commands = scenario.get("commands") or []
    expect = scenario.get("expect") or []
    timeout = float(scenario.get("timeout_seconds") or 40)
    delay_ms = int(scenario.get("stdin_delay_ms") or 150)

    log_dir = TMP_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{name}.log"

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTEST_CURRENT_TEST", "scripted-scenario")

    # Quick bootstrap: ensure state/db/schema exists without reinstalling the project each run.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    run([PY_EXE, "tools/sqlite_admin.py", "init"], cwd=ROOT, env=env, check=False, stdout=PIPE, stderr=STDOUT, text=True)
    # Import catalogs if empty (idempotent, cheap).
    run([PY_EXE, "tools/sqlite_admin.py", "catalog-import-items"], cwd=ROOT, env=env, check=False, stdout=PIPE, stderr=STDOUT, text=True)
    if not DB_PATH.exists():
        DB_PATH.touch()

    proc = Popen(
        [PY_EXE, "-m", "mutants"],
        cwd=ROOT,
        stdin=PIPE,
        stdout=PIPE,
        stderr=STDOUT,
        text=True,
        env=env,
    )

    cmd_text = "\n".join(commands) + "\n"
    try:
        out, _ = proc.communicate(input=cmd_text, timeout=timeout)
    except Exception:
        try:
            proc.kill()
        finally:
            out = proc.stdout.read() if proc.stdout else ""

    log_path.write_text(out or "", encoding="utf-8")

    # Simple ordered substring checks.
    idx = 0
    joined = out or ""
    for token in expect:
        pos = joined.find(token, idx)
        if pos == -1:
            print(f"[FAIL] missing expected text: {token!r}; log saved to {log_path}")
            return 1
        idx = pos + len(token)

    print(f"[OK] Scenario '{name}' passed. Log: {log_path}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run scripted Mutants scenario.")
    parser.add_argument("scenario", type=Path, help="Path to scenario JSON file.")
    args = parser.parse_args(argv)
    return run_scenario(args.scenario)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
