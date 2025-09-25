#!/usr/bin/env python3
"""Expand legacy item power fields into their ranged equivalents.

Usage::
    python scripts/expand_item_power_fields.py [path ...]

Paths default to ``state/items/catalog.json``. Files are rewritten in place.

The migration fills in ``base_power_melee``/``base_power_bolt`` and
``poison_melee``/``poison_bolt`` pairs when legacy ``base_power`` or
``poisonous``/``poison_power`` keys are present.  Legacy keys are removed once
expansion completes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"yes", "true", "on", "1"}:
            return True
        if token in {"no", "false", "off", "0"}:
            return False
    return bool(value)


def _expand_item(entry: dict[str, Any]) -> None:
    base_power = entry.get("base_power")
    melee_power = entry.get("base_power_melee")
    bolt_power = entry.get("base_power_bolt")

    base_value = _coerce_int(base_power)
    if base_value is not None:
        if melee_power is None:
            entry["base_power_melee"] = base_value
        if bolt_power is None:
            entry["base_power_bolt"] = base_value
    entry.pop("base_power", None)

    poison_flag = _coerce_bool(entry.get("poisonous"))
    poison_power = _coerce_int(entry.get("poison_power"))

    if poison_flag is not None:
        if entry.get("poison_melee") is None:
            entry["poison_melee"] = poison_flag
        if entry.get("poison_bolt") is None:
            entry["poison_bolt"] = poison_flag

        if poison_flag:
            melee_poison_power = entry.get("poison_melee_power")
            bolt_poison_power = entry.get("poison_bolt_power")
            if melee_poison_power is None:
                entry["poison_melee_power"] = poison_power or 0
            if bolt_poison_power is None:
                entry["poison_bolt_power"] = poison_power or 0
        else:
            # Ensure explicit False flags don't leave stale power fields.
            if poison_power is None:
                entry.pop("poison_melee_power", None)
                entry.pop("poison_bolt_power", None)

    entry.pop("poisonous", None)
    entry.pop("poison_power", None)


def _walk(obj: Any) -> None:
    if isinstance(obj, dict):
        if "item_id" in obj:
            _expand_item(obj)
        for value in obj.values():
            _walk(value)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item)


def _process(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    _walk(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=["state/items/catalog.json"])
    args = parser.parse_args()

    for raw_path in args.paths:
        _process(Path(raw_path))


if __name__ == "__main__":
    main()
