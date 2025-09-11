from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


DEFAULT_WIDTH = 80


@dataclass
class Theme:
    """UI theme controlling width, palette source and ANSI toggle."""

    name: str
    width: int
    colors_path: Optional[str]
    ansi_enabled: bool
    palette: Dict[str, str]


def load_theme(path: str) -> Theme:
    p = Path(path)
    data: Dict[str, str] = {}
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    width = int(data.get("width", data.get("WIDTH", DEFAULT_WIDTH)))
    name = data.get("name", p.stem if p.exists() else "default")
    colors_path = data.get("colors_path")
    ansi_enabled = bool(data.get("ansi_enabled", True))
    palette: Dict[str, str] = {}  # legacy palettes no longer used
    return Theme(
        name=name,
        width=width,
        colors_path=colors_path,
        ansi_enabled=ansi_enabled,
        palette=palette,
    )
