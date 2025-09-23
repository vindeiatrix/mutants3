#!/usr/bin/env python3
"""Bulk import monsters from a generator JSON payload."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from mutants.services import monsters_state
from mutants.services.monsters_importer import (
    MonsterImportError,
    print_report,
    run_import,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import monsters into the game state.")
    parser.add_argument("input_path", help="Path to the generator JSON file (array of monsters).")
    parser.add_argument(
        "--state-path",
        default=str(monsters_state.DEFAULT_MONSTERS_PATH),
        help="Target monsters state path (defaults to state/monsters/instances.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and show the summary without writing any changes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input_path)
    state_path = Path(args.state_path)

    try:
        report = run_import(input_path, dry_run=args.dry_run, state_path=state_path)
    except MonsterImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_report(report, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
