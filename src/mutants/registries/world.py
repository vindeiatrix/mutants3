# src/mutants/registries/world.py
"""
World registry for mutable map years (centuries).

- One JSON file per year at: state/world/<year>.json
- JSON shape accepted on load:
    * A list of tile dicts: [ { "pos":[year,x,y], "header_idx":..., "edges":{...}, ... }, ... ]
      OR
    * An object with "tiles": { "tiles": [ ... ] }  (anything else is preserved in "meta")
- In-memory:
    * YearWorld stores tiles keyed by (x, y) and tracks bounds for boundary checks.
    * Mutations mirror edge changes to the adjacent tile's opposite edge and forbid edits
      to boundary edges (base == 2) or edges that lead outside the map bounds.

Edge model (per tile):
    edges: { "N": {...}, "S": {...}, "E": {...}, "W": {...} }
    each edge: { base: int, gate_state: int, key_type: int|null, spell_block: int }
      base: 0=open, 1=terrain_block, 2=boundary, 3=gate
      gate_state: 0=open, 1=closed, 2=locked
      spell_block: 0=none, 1=ice_wall, 2=ion_field
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from mutants.io.atomic import atomic_write_json

WORLD_DIR = Path("state/world")

# Direction helpers
DIRS = ("N", "S", "E", "W")
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
DELTA = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}

BASE_OPEN = 0
BASE_TERRAIN = 1
BASE_BOUNDARY = 2
BASE_GATE = 3

GATE_OPEN = 0
GATE_CLOSED = 1
GATE_LOCKED = 2


def _edge_defaults(edge: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a normalized edge dict with all expected keys present."""
    e = dict(edge or {})
    e.setdefault("base", BASE_OPEN)
    e.setdefault("gate_state", GATE_OPEN)
    e.setdefault("key_type", None)
    e.setdefault("spell_block", 0)
    return e


def _tile_defaults(t: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a tile dict and ensure required fields exist."""
    t = dict(t)
    # Normalize booleans and nulls as-is (we don't coerce types here).
    t.setdefault("header_idx", 0)
    t.setdefault("store_id", None)
    t.setdefault("dark", False)
    t.setdefault("area_locked", False)

    edges = t.get("edges") or {}
    t["edges"] = {d: _edge_defaults(edges.get(d)) for d in DIRS}
    # Pos must be [year, x, y]
    pos = t.get("pos")
    if not (isinstance(pos, list) and len(pos) == 3):
        raise ValueError(f"tile missing/invalid pos: {pos!r}")
    return t


class YearWorld:
    """
    Mutable view of a single year's tiles with boundary safety and mirrored edges.
    """

    def __init__(self, year: int, tiles: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None):
        self.year = int(year)
        self._tiles_by_xy: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self._dirty = False
        self._save_shape: str = "list"  # "list" or "object"
        self._meta: Dict[str, Any] = meta or {}

        # Load tiles and compute bounds
        min_x = min_y = 10**9
        max_x = max_y = -10**9
        for raw in tiles:
            t = _tile_defaults(raw)
            y, x, y2 = t["pos"][0], t["pos"][1], t["pos"][2]
            if int(y) != int(self.year):
                raise ValueError(f"tile year {y} != world year {self.year}")
            x_i, y_i = int(x), int(y2)
            self._tiles_by_xy[(x_i, y_i)] = t
            min_x = min(min_x, x_i); max_x = max(max_x, x_i)
            min_y = min(min_y, y_i); max_y = max(max_y, y_i)

        if min_x == 10**9:
            # empty world; set degenerate bounds
            min_x = max_x = min_y = max_y = 0

        self._bounds = (min_x, max_x, min_y, max_y)

    # ---------- basic queries ----------

    @property
    def bounds(self) -> Tuple[int, int, int, int]:
        """(min_x, max_x, min_y, max_y)"""
        return self._bounds

    def iter_tiles(self) -> Iterable[Dict[str, Any]]:
        return self._tiles_by_xy.values()

    def get_tile(self, x: int, y: int) -> Optional[Dict[str, Any]]:
        return self._tiles_by_xy.get((int(x), int(y)))

    # ---------- helpers ----------

    def _is_outside_bounds(self, x: int, y: int) -> bool:
        min_x, max_x, min_y, max_y = self._bounds
        return not (min_x <= x <= max_x and min_y <= y <= max_y)

    def _neighbor_xy(self, x: int, y: int, dir_: str) -> Tuple[int, int]:
        dx, dy = DELTA[dir_]
        return x + dx, y + dy

    def _raise_if_boundary_edge(self, t: Dict[str, Any], dir_: str) -> None:
        if t["edges"][dir_]["base"] == BASE_BOUNDARY:
            raise ValueError(f"Cannot modify boundary edge {dir_} at {tuple(t['pos'][1:])}")

    def _touch(self) -> None:
        self._dirty = True

    # ---------- tile field mutations ----------

    def set_store(self, x: int, y: int, store_id: Optional[int]) -> None:
        t = self.get_tile(x, y)
        if not t:
            raise KeyError(f"Unknown tile at ({x},{y})")
        t["store_id"] = store_id
        self._touch()

    def set_dark(self, x: int, y: int, dark: bool) -> None:
        t = self.get_tile(x, y)
        if not t:
            raise KeyError(f"Unknown tile at ({x},{y})")
        t["dark"] = bool(dark)
        self._touch()

    def set_area_locked(self, x: int, y: int, locked: bool) -> None:
        t = self.get_tile(x, y)
        if not t:
            raise KeyError(f"Unknown tile at ({x},{y})")
        t["area_locked"] = bool(locked)
        self._touch()

    # ---------- edge mutations (mirrored) ----------

    def set_edge(
        self,
        x: int,
        y: int,
        dir_: str,
        *,
        base: Optional[int] = None,
        gate_state: Optional[int] = None,
        key_type: Optional[Optional[int]] = None,
        spell_block: Optional[int] = None,
        force_gate_base: bool = False,
    ) -> None:
        """
        Mutate edge fields for tile (x,y) in direction dir_ and mirror to neighbor.
        - dir_ must be one of "N","S","E","W".
        - If base is provided and the current or new base would be a boundary (2), raises.
        - If neighbor exists, mirror the same fields to its opposite edge.
        - If neighbor is outside bounds, the change is allowed (non-boundary) but not mirrored.

        force_gate_base=True: if changing gate_state on a non-gate edge, first set base=3.
        """
        if dir_ not in DIRS:
            raise ValueError(f"dir must be one of {DIRS}, got {dir_!r}")
        t = self.get_tile(x, y)
        if not t:
            raise KeyError(f"Unknown tile at ({x},{y})")

        # disallow direct edits to explicit boundary edges
        self._raise_if_boundary_edge(t, dir_)

        e = t["edges"][dir_]
        new_e = dict(e)  # local copy so we can reason then apply
        if base is not None:
            if base == BASE_BOUNDARY or e.get("base") == BASE_BOUNDARY:
                raise ValueError("Cannot set or modify a boundary edge")
            new_e["base"] = int(base)

        if gate_state is not None:
            if new_e.get("base", e.get("base")) != BASE_GATE:
                if force_gate_base:
                    new_e["base"] = BASE_GATE
                else:
                    raise ValueError("Changing gate_state on a non-gate edge (set base=3 or pass force_gate_base=True)")
            new_e["gate_state"] = int(gate_state)

        if key_type is not None:
            new_e["key_type"] = None if key_type is None else int(key_type)

        if spell_block is not None:
            new_e["spell_block"] = int(spell_block)

        # Apply to this tile
        t["edges"][dir_] = new_e
        self._touch()

        # Mirror to neighbor if present and legal
        nx, ny = self._neighbor_xy(int(x), int(y), dir_)
        if self._is_outside_bounds(nx, ny):
            return  # nothing to mirror
        nt = self.get_tile(nx, ny)
        if not nt:
            return
        opp = OPPOSITE[dir_]
        # Disallow mirroring into a boundary edge on the neighbor
        if nt["edges"][opp]["base"] == BASE_BOUNDARY or new_e.get("base") == BASE_BOUNDARY:
            return
        ne = dict(nt["edges"][opp])
        # Mirror only the fields that changed
        for k in ("base", "gate_state", "key_type", "spell_block"):
            if ((k == "base" and base is not None) or
                (k == "gate_state" and gate_state is not None) or
                (k == "key_type" and key_type is not None) or
                (k == "spell_block" and spell_block is not None)):
                ne[k] = new_e[k]
        nt["edges"][opp] = ne
        self._touch()

    # convenience wrappers

    def clear_terrain(self, x: int, y: int, dir_: str) -> None:
        """Set edge base to open (0) on (x,y,dir_) and mirror."""
        self.set_edge(x, y, dir_, base=BASE_OPEN)

    def open_gate(self, x: int, y: int, dir_: str) -> None:
        """Ensure edge is a gate (base=3) and set gate_state=open (0), mirrored."""
        self.set_edge(x, y, dir_, base=BASE_GATE, gate_state=GATE_OPEN)

    def close_gate(self, x: int, y: int, dir_: str) -> None:
        """Ensure edge is a gate and set gate_state=closed (1), mirrored."""
        # If it's not already a gate, set base=3 then close.
        t = self.get_tile(x, y)
        if not t:
            raise KeyError(f"Unknown tile at ({x},{y})")
        if t["edges"][dir_]["base"] != BASE_GATE:
            self.set_edge(x, y, dir_, base=BASE_GATE)
        self.set_edge(x, y, dir_, gate_state=GATE_CLOSED, force_gate_base=True)

    def lock_gate(self, x: int, y: int, dir_: str, key_type: int) -> None:
        """Ensure edge is a gate and set gate_state=locked (2) with key_type, mirrored."""
        t = self.get_tile(x, y)
        if not t:
            raise KeyError(f"Unknown tile at ({x},{y})")
        if t["edges"][dir_]["base"] != BASE_GATE:
            self.set_edge(x, y, dir_, base=BASE_GATE)
        self.set_edge(x, y, dir_, gate_state=GATE_LOCKED, key_type=key_type, force_gate_base=True)

    # ---------- persistence ----------

    def save(self, out_path: Optional[Path] = None) -> None:
        """Atomic write this year's tiles back to disk (list shape by default)."""
        if not self._dirty and out_path is None:
            return  # nothing to do if caller didn't force a path

        path = out_path or (WORLD_DIR / f"{self.year}.json")
        # Preserve original shape if meta indicates object form; otherwise save as list.
        if self._save_shape == "object" and self._meta:
            payload = dict(self._meta)
            payload["tiles"] = list(self.iter_tiles())
        else:
            payload = list(self.iter_tiles())
        atomic_write_json(path, payload)
        self._dirty = False


class WorldRegistry:
    """
    Lazy-loading container for multiple YearWorlds.
    Usage:
        world = WorldRegistry()
        yw = world.load_year(2000)
        t = yw.get_tile(0, 0)
        yw.open_gate(1, 0, "N")
        yw.save()  # or world.save_all()
    """

    def __init__(self, base_dir: Path = WORLD_DIR):
        self.base_dir = Path(base_dir)
        self._by_year: Dict[int, YearWorld] = {}

    def load_year(self, year: int) -> YearWorld:
        year = int(year)
        if year in self._by_year:
            return self._by_year[year]
        path = self.base_dir / f"{year}.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing world file: {path}")

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "tiles" in data:
            tiles = data["tiles"]
            meta = {k: v for k, v in data.items() if k != "tiles"}
            yw = YearWorld(year, tiles, meta=meta)
            yw._save_shape = "object"
        elif isinstance(data, list):
            yw = YearWorld(year, data, meta=None)
            yw._save_shape = "list"
        else:
            raise ValueError(f"World file for {year} must be a list or an object with 'tiles'")

        self._by_year[year] = yw
        return yw

    def get_year(self, year: int) -> Optional[YearWorld]:
        return self._by_year.get(int(year))

    def save_all(self) -> None:
        for y, yw in list(self._by_year.items()):
            yw.save(self.base_dir / f"{y}.json")


# Convenience module-level loader if you prefer functions over a registry object.
_default_world_registry: Optional[WorldRegistry] = None

def load_year(year: int) -> YearWorld:
    global _default_world_registry
    if _default_world_registry is None:
        _default_world_registry = WorldRegistry()
    return _default_world_registry.load_year(year)

def save_all() -> None:
    global _default_world_registry
    if _default_world_registry:
        _default_world_registry.save_all()
