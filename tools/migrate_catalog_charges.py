#!/usr/bin/env python3
"""One-shot codemod to migrate catalog charge fields.

Usage:
    python tools/migrate_catalog_charges.py [path ...]

Paths default to ``state/items/catalog.json``. Files are rewritten in place
with stable key ordering and pretty printing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _migrate_item(it: dict[str, Any]) -> None:
    if "charges_start" in it:
        it["charges_max"] = int(it["charges_start"])
        it.pop("charges_start", None)

    if it.get("ranged"):
        it["spawnable"] = False
        if it.get("charges_max", 0) > 0:
            it["uses_charges"] = True
    else:
        if not it.get("uses_charges"):
            it.pop("uses_charges", None)
            if not it.get("charges_max"):
                it.pop("charges_max", None)


def _process(path: Path) -> None:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "items" in data:
        items = data["items"]
    else:
        items = data
    for it in items:
        _migrate_item(it)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=["state/items/catalog.json"])
    args = ap.parse_args()
    for p in args.paths:
        _process(Path(p))


if __name__ == "__main__":
    main()

