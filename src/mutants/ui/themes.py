from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


DEFAULTS = {"WIDTH": 80, "RESET": "\x1b[0m"}


@dataclass
class Theme:
    name: str
    palette: Dict[str, str]
    width: int


def load_theme(path: str) -> Theme:
    p = Path(path)
    data: Dict[str, str] = {}
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    palette = {**DEFAULTS, **{k: str(v) for k, v in data.items() if k != "WIDTH"}}
    width = int(data.get("WIDTH", DEFAULTS["WIDTH"]))
    name = p.stem if p.exists() else "default"
    return Theme(name=name, palette=palette, width=width)
