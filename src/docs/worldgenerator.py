# build_world_json.py
# Generate a per-century JSON world file (with optional random stores).
# python worldgenerator.py --headers .\room_headers.py --out .\2000.json --year 2000 --maze 0.15 --center-open 2 --store-rate 0.015 --seed 2000
# python worldgenerator.py --headers .\room_headers.py --out .\2100.json --year 2100 --maze 0.25 --center-open 2 --store-rate 0.020 --seed 2100
# python worldgenerator.py --headers .\room_headers.py --out .\2200.json --year 2200 --p-block 0.20 --p-gate 0.04 --center-open 1 --store-rate 0.020 --seed 2200
# python worldgenerator.py --headers .\room_headers.py --out .\2300.json --year 2300 --maze 0.35 --center-open 1 --store-rate 0.020 --seed 2300
# python worldgenerator.py --headers .\room_headers.py --out .\2400.json --year 2400 --p-block 0.28 --p-gate 0.06 --center-open 1 --store-rate 0.022 --seed 2400
# python worldgenerator.py --headers .\room_headers.py --out .\2500.json --year 2500 --maze 0.45 --center-open 1 --store-rate 0.025 --seed 2500
# python worldgenerator.py --headers .\room_headers.py --out .\2600.json --year 2600 --p-block 0.32 --p-gate 0.08 --center-open 0 --store-rate 0.020 --seed 2600
# python worldgenerator.py --headers .\room_headers.py --out .\2700.json --year 2700 --maze 0.55 --center-open 1 --store-rate 0.020 --seed 2700
# python worldgenerator.py --headers .\room_headers.py --out .\2800.json --year 2800 --p-block 0.38 --p-gate 0.10 --center-open 1 --store-rate 0.025 --seed 2800
# python worldgenerator.py --headers .\room_headers.py --out .\2900.json --year 2900 --maze 0.70 --center-open 0 --store-rate 0.030 --seed 2900
# python worldgenerator.py --headers .\room_headers.py --out .\3000.json --year 3000 --p-block 0.42 --p-gate 0.12 --center-open 1 --store-rate 0.030 --seed 3000

#
# Key features
# - Grid: square, even `--size` recommended. Coords are x,y ∈ [-(size/2) .. (size/2-1)] with (0,0) at center.
# - Center area: force a fully-open square of radius `--center-open` (1 => 3x3).
# - “Maze-ness”: control interior edges via either:
#     * one knob: `--maze 0..1`  (0 = open fields, 1 = very maze-like)
#     * or direct per-edge probs: `--p-block P` and/or `--p-gate P` (override `--maze`).
#       Exactly how it works (for each interior edge):
#         r = random() in [0,1)
#         if r < p_block      → TERRAIN_BLOCK (a wall)
#         elif r < p_block+p_gate → GATE (starts OPEN)
#         else                → OPEN
#       Example settings:
#         --p-block 0.10 --p-gate 0.02  → mostly open; rare walls and a few gates
#         --p-block 0.25 --p-gate 0.05  → chunkier walls with some gates (≈25% walls, 5% gates, 70% open)
#         --p-block 0.45 --p-gate 0.10  → dense maze (≈45% walls, 10% gates, 45% open)
#       NOTE: We never place gates on hard boundaries; boundaries are set first and excluded from randomization.
# - Stores: random placement controlled by `--store-rate` (fraction of tiles). Requires your
#           room_headers.py to define STORE_FOR_SALE_IDX; store tiles get that header and a store_id.
#           We also emit a `stores` array with minimal metadata (id, pos, original_cost, state='for_sale').
# - Output JSON:
#   {
#     "schema_version": 2,
#     "year": 2000,
#     "size": 30,
#     "tiles": [ { "pos":[year,x,y], "header_idx":..., "store_id":..., "dark":..., "area_locked":..., "edges": {...} }, ... ],
#     "stores": [ {"id":1,"pos":[2000,x,y],"original_cost":25000,"state":"for_sale"}, ... ],
#     "params": {...}
#   }
#
# Usage:
#   python build_world_json.py --headers path/to/room_headers.py --out state/world/2000.json
#   python build_world_json.py --headers room_headers.py --out 2800.json --year 2800 --size 30 --center-open 1 --maze 0.35 --seed 123
#   python build_world_json.py --headers room_headers.py --out 2000.json --year 2000 --p-block 0.25 --p-gate 0.05 --store-rate 0.02
#
# Enums used in JSON (ints):
#   base:       0=open, 1=terrain_block, 2=boundary, 3=gate
#   gate_state: 0=open, 1=closed, 2=locked
#   spell_block:0=none, 1=ice_wall, 2=ion_field

from __future__ import annotations
import argparse, json, os, random, sys
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Dict, Tuple
import importlib.util

SCHEMA_VERSION = 2

# -------------------------
# Enums (small ints)
# -------------------------
class Base(IntEnum):
    OPEN = 0
    TERRAIN_BLOCK = 1
    BOUNDARY = 2
    GATE = 3

class GateState(IntEnum):
    OPEN = 0
    CLOSED = 1
    LOCKED = 2

class SpellBlock(IntEnum):
    NONE = 0
    ICE_WALL = 1
    ION_FIELD = 2

# -------------------------
# Records
# -------------------------
@dataclass
class Edge:
    base: int = Base.OPEN
    gate_state: int = GateState.OPEN
    key_type: Optional[int] = None
    spell_block: int = SpellBlock.NONE

    def to_json(self) -> dict:
        return {
            "base": int(self.base),
            "gate_state": int(self.gate_state),
            "key_type": self.key_type,
            "spell_block": int(self.spell_block),
        }

@dataclass
class TileRecord:
    pos: tuple[int,int,int]          # (year, x, y)
    header_idx: int
    store_id: Optional[int] = None
    dark: bool = False
    area_locked: bool = False
    edges: Dict[str, Edge] = None    # "N","S","E","W"

    def to_json(self) -> dict:
        return {
            "pos": list(self.pos),
            "header_idx": self.header_idx,
            "store_id": self.store_id,
            "dark": self.dark,
            "area_locked": self.area_locked,
            "edges": {d: e.to_json() for d, e in self.edges.items()},
        }

# -------------------------
# Utilities
# -------------------------
def load_room_headers(module_path: str) -> tuple[list[str], Optional[int]]:
    """Load ROOM_HEADERS (and optional STORE_FOR_SALE_IDX) from a Python file."""
    spec = importlib.util.spec_from_file_location("room_headers", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import room headers from {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    headers = getattr(mod, "ROOM_HEADERS", None)
    if not isinstance(headers, list) or not headers:
        raise RuntimeError("ROOM_HEADERS must be a non-empty list in the headers file.")
    store_idx = getattr(mod, "STORE_FOR_SALE_IDX", None)
    return headers, store_idx

def bounds_for_size(size: int) -> range:
    half = size // 2
    return range(-half, half)  # e.g., size=30 → -15..14

def in_bounds(x: int, y: int, size: int) -> bool:
    r = bounds_for_size(size)
    return (x in r) and (y in r)

def opposite(d: str) -> str:
    return {"N":"S", "S":"N", "E":"W", "W":"E"}[d]

def neighbor(x:int, y:int, d:str) -> tuple[int,int]:
    if d == "N": return (x, y+1)
    if d == "S": return (x, y-1)
    if d == "E": return (x+1, y)
    if d == "W": return (x-1, y)
    raise ValueError(d)

def pick_header_index(headers: list[str], store_idx: Optional[int]) -> int:
    idxs = [i for i in range(len(headers)) if (store_idx is None or i != int(store_idx))]
    return random.choice(idxs)

def store_price_for_year(year: int) -> int:
    # 2000→25000, each +100 years adds +25000: 2100→50000, 2200→75000, ...
    step = (year - 2000) // 100
    return 25000 * (step + 1)

# -------------------------
# Generation
# -------------------------
def gen_world(year: int, size: int, center_open: int,
              p_block: float, p_gate: float,
              headers: list[str], store_idx: Optional[int],
              store_rate: float) -> tuple[list[TileRecord], list[dict]]:
    """
    Returns (tiles, stores).
    - store_rate: fraction of tiles to mark as stores (0.0..1.0). If STORE_FOR_SALE_IDX is missing, no stores are placed.
    """
    xr = yr = bounds_for_size(size)

    # 1) Create all tiles (fully open, random non-store headers)
    tiles: Dict[Tuple[int,int], TileRecord] = {}
    for x in xr:
        for y in yr:
            tiles[(x,y)] = TileRecord(
                pos=(year, x, y),
                header_idx=pick_header_index(headers, store_idx),
                store_id=None,
                dark=False,
                area_locked=False,
                edges={"N": Edge(), "S": Edge(), "E": Edge(), "W": Edge()},
            )

    # 2) Boundaries first (and never place gates here)
    for x in xr:
        for y in yr:
            t = tiles[(x,y)]
            for d in ("N","S","E","W"):
                nx, ny = neighbor(x, y, d)
                if not in_bounds(nx, ny, size):
                    e = t.edges[d]
                    e.base = Base.BOUNDARY
                    e.gate_state = GateState.OPEN
                    e.key_type = None
                    e.spell_block = SpellBlock.NONE

    # 3) Open center block
    def in_center_block(x:int, y:int) -> bool:
        return (-center_open <= x <= center_open) and (-center_open <= y <= center_open)

    for x in xr:
        for y in yr:
            if not in_center_block(x, y):
                continue
            t = tiles[(x,y)]
            for d in ("N","S","E","W"):
                nx, ny = neighbor(x, y, d)
                if in_bounds(nx, ny, size):
                    t.edges[d].base = Base.OPEN
                    t.edges[d].gate_state = GateState.OPEN
                    t.edges[d].key_type = None
                    t.edges[d].spell_block = SpellBlock.NONE
                    opp = tiles[(nx,ny)].edges[opposite(d)]
                    opp.base = Base.OPEN
                    opp.gate_state = GateState.OPEN
                    opp.key_type = None
                    opp.spell_block = SpellBlock.NONE

    # 4) Randomize interior edges (E/N only; mirror to neighbors). Skip boundaries & forced-open center.
    for x in xr:
        for y in yr:
            if in_center_block(x, y):
                continue
            here = tiles[(x,y)]
            # EAST
            nx, ny = x+1, y
            if in_bounds(nx, ny, size) and not in_center_block(nx, ny):
                e_here = here.edges["E"]
                e_there = tiles[(nx,ny)].edges["W"]
                if e_here.base != Base.BOUNDARY and e_there.base != Base.BOUNDARY:
                    r = random.random()
                    if r < p_block:
                        e_here.base = e_there.base = Base.TERRAIN_BLOCK
                        e_here.gate_state = e_there.gate_state = GateState.OPEN
                        e_here.key_type = e_there.key_type = None
                        e_here.spell_block = e_there.spell_block = SpellBlock.NONE
                    elif r < p_block + p_gate:
                        e_here.base = e_there.base = Base.GATE        # GATE (default OPEN)
                        e_here.gate_state = e_there.gate_state = GateState.OPEN
                        e_here.key_type = e_there.key_type = None
                        e_here.spell_block = e_there.spell_block = SpellBlock.NONE
            # NORTH
            nx, ny = x, y+1
            if in_bounds(nx, ny, size) and not in_center_block(nx, ny):
                n_here = here.edges["N"]
                s_there = tiles[(nx,ny)].edges["S"]
                if n_here.base != Base.BOUNDARY and s_there.base != Base.BOUNDARY:
                    r = random.random()
                    if r < p_block:
                        n_here.base = s_there.base = Base.TERRAIN_BLOCK
                        n_here.gate_state = s_there.gate_state = GateState.OPEN
                        n_here.key_type = s_there.key_type = None
                        n_here.spell_block = s_there.spell_block = SpellBlock.NONE
                    elif r < p_block + p_gate:
                        n_here.base = s_there.base = Base.GATE
                        n_here.gate_state = s_there.gate_state = GateState.OPEN
                        n_here.key_type = s_there.key_type = None
                        n_here.spell_block = s_there.spell_block = SpellBlock.NONE

    # 5) Place stores (optional)
    stores: list[dict] = []
    if store_idx is not None and store_rate > 0.0:
        all_positions = [(x, y) for x in xr for y in yr if not in_center_block(x, y)]
        count = max(0, min(len(all_positions), int(round(store_rate * len(all_positions)))))
        chosen = set(random.sample(all_positions, count)) if count > 0 else set()
        next_id = 1
        price = store_price_for_year(year)

        for (x, y) in chosen:
            t = tiles[(x, y)]
            t.header_idx = int(store_idx)
            t.store_id = next_id
            stores.append({
                "id": next_id,
                "pos": [year, x, y],
                "original_cost": price,     # number formatting (no commas) happens at render-time
                "state": "for_sale"
            })
            next_id += 1
    elif store_rate > 0.0 and store_idx is None:
        print("[warn] STORE_FOR_SALE_IDX not defined in room headers; skipping store placement.", file=sys.stderr)

    # Return flat list of tiles in a stable order
    tiles_list = [tiles[(x,y)] for x in xr for y in yr]
    return tiles_list, stores

def write_json_atomic(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

# -------------------------
# CLI
# -------------------------
def main():
    ap = argparse.ArgumentParser(description="Generate a per-century world JSON (with optional stores).")
    ap.add_argument("--headers", required=True, help="Path to room_headers.py (must define ROOM_HEADERS; STORE_FOR_SALE_IDX enables store placement)")
    ap.add_argument("--out", required=True, help="Output JSON path, e.g., state/world/2000.json")
    ap.add_argument("--year", type=int, default=2000, help="Century/year (e.g., 2000)")
    ap.add_argument("--size", type=int, default=30, help="Grid size (width=height); even recommended")
    ap.add_argument("--center-open", type=int, default=1, help="Center open radius (1 => 3x3)")
    ap.add_argument("--maze", type=float, default=0.35, help="0.0=open fields … 1.0=very maze-like")
    ap.add_argument("--seed", type=int, default=1337, help="Random seed")

    # Explicit probability overrides (take precedence over --maze if provided)
    ap.add_argument("--p-block", type=float, default=None, help="Prob. of interior TERRAIN_BLOCK per edge [0..1]")
    ap.add_argument("--p-gate", type=float, default=None, help="Prob. of interior GATE (OPEN) per edge [0..1]")

    # Stores
    ap.add_argument("--store-rate", type=float, default=0.02, help="Fraction of tiles to place as stores [0..1]; requires STORE_FOR_SALE_IDX")

    args = ap.parse_args()

    if args.size <= 0:
        ap.error("--size must be > 0")
    if args.center_open < 0:
        ap.error("--center-open must be >= 0")
    if args.p_block is not None and not (0.0 <= args.p_block <= 1.0):
        ap.error("--p-block must be in [0,1]")
    if args.p_gate is not None and not (0.0 <= args.p_gate <= 1.0):
        ap.error("--p-gate must be in [0,1]")
    if not (0.0 <= args.store_rate <= 1.0):
        ap.error("--store-rate must be in [0,1]")

    # Map “maze” to probabilities unless explicitly overridden
    if args.p_block is None or args.p_gate is None:
        maze = max(0.0, min(1.0, args.maze))
        p_block = (0.06 + 0.34 * maze) if args.p_block is None else args.p_block
        p_gate  = (0.03 + 0.10 * maze) if args.p_gate  is None else args.p_gate
    else:
        p_block, p_gate = args.p_block, args.p_gate

    headers, store_idx = load_room_headers(args.headers)
    random.seed(args.seed)

    tiles, stores = gen_world(
        year=args.year,
        size=args.size,
        center_open=args.center_open,
        p_block=p_block,
        p_gate=p_gate,
        headers=headers,
        store_idx=store_idx,
        store_rate=args.store_rate,
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "year": args.year,
        "size": args.size,
        "tiles": [t.to_json() for t in tiles],
        "stores": stores,  # minimal store registry for convenience
        "params": {
            "center_open": args.center_open,
            "p_block": p_block,
            "p_gate": p_gate,
            "store_rate": args.store_rate,
            "seed": args.seed,
            "headers_source": os.path.basename(args.headers),
        },
    }

    write_json_atomic(args.out, payload)
    print(f"Wrote {len(tiles)} tiles to {args.out} (year={args.year}, size={args.size}x{args.size}, stores={len(stores)})")
    print(f"center_open={args.center_open}  p_block={p_block:.3f}  p_gate={p_gate:.3f}  store_rate={args.store_rate:.3f}  seed={args.seed}")

if __name__ == "__main__":
    main()
