"""Toggle state debug logging without touching environment variables.

Usage:
    python tools/state_debug_toggle.py --enable
    python tools/state_debug_toggle.py --disable

Creates or removes state/logs/state_debug.flag, which turns on the
state_debug logger (see mutants.services.state_debug).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from mutants.state import state_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Toggle state debug logging flag.")
    parser.add_argument("--enable", action="store_true", help="Enable state debug logging")
    parser.add_argument("--disable", action="store_true", help="Disable state debug logging")
    args = parser.parse_args()

    if args.enable and args.disable:
        parser.error("Choose either --enable or --disable, not both.")

    flag = Path(state_path("logs", "state_debug.flag"))
    flag.parent.mkdir(parents=True, exist_ok=True)

    if args.disable:
        if flag.exists():
            flag.unlink()
        print("State debug logging disabled (flag removed).")
        return 0

    # Default to enable when no explicit flag provided
    if not args.enable and not args.disable:
        args.enable = True

    flag.touch()
    print(f"State debug logging enabled via {flag}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
