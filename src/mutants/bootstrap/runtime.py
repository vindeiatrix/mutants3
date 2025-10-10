from __future__ import annotations

import json
import os
import re
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from mutants.io.atomic import atomic_write_json
from mutants.state import STATE_ROOT, state_path
from . import validator
from .daily_litter import run_daily_litter

LOG = logging.getLogger(__name__)
WORLD_DEBUG = os.getenv("WORLD_DEBUG") == "1"
WORLD_STRICT = os.getenv("WORLD_STRICT") == "1"

STATE = STATE_ROOT
WORLD_DIR = state_path("world")
ITEMS_DIR = state_path("items")
MONS_DIR = state_path("monsters")
THEMES_DIR = state_path("ui", "themes")
LOGS_DIR = state_path("logs")
CONFIG_PATH = state_path("config.json")
COLORS_PATH = str(state_path("ui", "colors.json"))

# ---------- public API ----------
def ensure_runtime() -> Dict:
    """
    Idempotent startup bootstrap:
      - ensure dirs exist
      - ensure themes exist (bbs.json, mono.json)
      - discover world years; if none, create a minimal world using config defaults
      - return a dict of discovered info (years, config, theme files)
    """
    ensure_dirs([WORLD_DIR, ITEMS_DIR, MONS_DIR, THEMES_DIR, LOGS_DIR])
    cfg = read_config()
    created_themes = ensure_theme_files(cfg.get("default_theme", "bbs"))
    years = discover_world_years()
    if not years:
        LOG.info(
            "[world] no world jsons found; cwd=%s world_dir=%s",
            Path.cwd(), WORLD_DIR.resolve()
        )
        if WORLD_STRICT:
            raise RuntimeError(
                f"No world JSONs found in {WORLD_DIR.resolve()} (cwd={Path.cwd()}). "
                "Set WORLD_STRICT=0 to allow minimal world creation."
            )
        year = int(cfg.get("default_world_year", 2000))
        size = int(cfg.get("default_world_size", 30))
        create_minimal_world(year=year, size=size, reason="no_worlds_discovered")
        years = [year]

    try:
        run_daily_litter()
    except Exception as e:
        logging.getLogger(__name__).warning("daily_litter skipped: %s", e)

    try:
        validator.run_on_boot()
    except Exception:
        if WORLD_DEBUG:
            LOG.exception("startup validator failed")
        else:
            raise

    return {"config": cfg, "years": sorted(years), "themes_created": created_themes}

def discover_world_years() -> List[int]:
    yrs = []
    for p in WORLD_DIR.glob("*.json"):
        m = re.fullmatch(r"(\d{3,4})\.json", p.name)
        if m:
            try:
                yrs.append(int(m.group(1)))
            except ValueError:
                pass
    yrs = sorted(set(yrs))
    if WORLD_DEBUG:
        LOG.debug("[world] discover_world_years dir=%s years=%s", WORLD_DIR.resolve(), yrs)
    return yrs

# ---------- helpers ----------
def ensure_dirs(paths: Iterable[Path]) -> None:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)

def read_config() -> Dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def ensure_theme_files(default_theme: str = "bbs") -> Dict[str, bool]:
    created = {"bbs": False, "mono": False}
    bbs = THEMES_DIR / "bbs.json"
    mono = THEMES_DIR / "mono.json"
    if not bbs.exists():
        atomic_write_json(bbs, _bbs_theme())
        created["bbs"] = True
    if not mono.exists():
        atomic_write_json(mono, _mono_theme())
        created["mono"] = True
    return created


def _bbs_theme() -> Dict[str, str]:
    return {
        "name": "bbs",
        "width": 80,
        "ansi_enabled": True,
        "colors_path": COLORS_PATH,
    }


def _mono_theme() -> Dict[str, str]:
    return {
        "name": "mono",
        "width": 80,
        "ansi_enabled": False,
        "colors_path": COLORS_PATH,
    }

def create_minimal_world(year: int, size: int = 30, *, reason: str = "unspecified") -> None:
    """
    Create a simple square world with boundaries on the outer rim and open cells inside.
    Tiles include JSON 'pos': [year, x, y] and minimal edge records.
    """
    LOG.warning(
        "[world] create_minimal_world reason=%s cwd=%s target_dir=%s",
        reason, Path.cwd(), WORLD_DIR.resolve()
    )
    half = size // 2
    tiles = []
    for y in range(-half, half):
        for x in range(-half, half):
            edges = {}
            for dir_code, dx, dy in (("N",0,1),("S",0,-1),("E",1,0),("W",-1,0)):
                nx, ny = x + dx, y + dy
                on_border = (nx < -half or nx >= half or ny < -half or ny >= half)
                base = 2 if on_border else 0  # 2=boundary, 0=open
                edges[dir_code] = {"base": base, "gate_state": 0, "key_type": None, "spell_block": 0}
            tiles.append({
                "pos": [year, x, y],
                "header_idx": 0,
                "store_id": None,
                "dark": False,
                "area_locked": False,
                "edges": edges
            })
    data = {"year": year, "size": size, "tiles": tiles}
    atomic_write_json(WORLD_DIR / f"{year}.json", data)
