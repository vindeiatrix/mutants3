#!/usr/bin/env python3
"""Convert legacy "spawnable": "yes"/"no" flags to JSON booleans.

Usage:
    python scripts/migrate_spawn_flags.py [path ...]

Paths default to ``state/items/catalog.json``. Files are rewritten in place.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _convert(obj: Any) -> None:
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == "spawnable" and isinstance(v, str):
                low = v.lower()
                if low == "yes":
                    obj[k] = True
                elif low == "no":
                    obj[k] = False
            else:
                _convert(v)
    elif isinstance(obj, list):
        for item in obj:
            _convert(item)


def _process(path: Path) -> None:
    data = json.loads(path.read_text())
    _convert(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=["state/items/catalog.json"])
    args = ap.parse_args()
    for p in args.paths:
        _process(Path(p))


if __name__ == "__main__":
    main()
