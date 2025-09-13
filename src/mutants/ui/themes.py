from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Any


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
    data: Dict[str, Any] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    width_raw = data.get("width", data.get("WIDTH", DEFAULT_WIDTH))
    try:
        width = int(width_raw)
    except (TypeError, ValueError):
        width = DEFAULT_WIDTH

    name = data.get("name", p.stem if p.exists() else "default")
    colors_path = data.get("colors_path") if isinstance(data.get("colors_path"), str) else None

    ansi_raw = data.get("ansi_enabled", True)
    if isinstance(ansi_raw, str):
        ansi_enabled = ansi_raw.lower() == "true"
    else:
        ansi_enabled = bool(ansi_raw)

    palette = data.get("palette") if isinstance(data.get("palette"), dict) else {}

    return Theme(
        name=name,
        width=width,
        colors_path=colors_path,
        ansi_enabled=ansi_enabled,
        palette=palette,
    )
