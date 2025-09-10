from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass
class Theme:
    name: str
    palette: Dict[str, str]
    width: int


def load_theme(path: str) -> Theme:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    width = int(data.pop("WIDTH", 80))
    if "RESET" not in data:
        data["RESET"] = "\x1b[0m"
    name = p.stem
    return Theme(name=name, palette=data, width=width)
