from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import time

from mutants.registries.world import (
    BASE_OPEN,
    BASE_BOUNDARY,
    BASE_GATE,
    GATE_OPEN,
)

DESC_AREA = "area continues."
DESC_ICE = "wall of ice."
DESC_FORCE = "ion force field."
DESC_GATE_OPEN = "open gate."
DESC_GATE_CLOSED = "closed gate."
CANON = {DESC_AREA, DESC_ICE, DESC_FORCE, DESC_GATE_OPEN, DESC_GATE_CLOSED}


@dataclass
class EdgeDecision:
    passable: bool
    descriptor: str
    reason_chain: List[Tuple[str, str]]
    cur_raw: Dict
    nbr_raw: Dict
    reason: str = "ok"


def _is_open(e: Dict) -> bool:
    base = e.get("base", BASE_OPEN)
    if base == BASE_OPEN:
        return True
    if base == BASE_GATE:
        return e.get("gate_state", GATE_OPEN) == GATE_OPEN
    if base == BASE_BOUNDARY:
        return False
    return False


def _passable_pair(a: Dict, b: Dict) -> bool:
    return _is_open(a) and _is_open(b)


def _block_reason(a: Dict, b: Dict) -> str:
    for e in (a, b):
        base = e.get("base")
        if base == BASE_GATE and e.get("gate_state", GATE_OPEN) != GATE_OPEN:
            return "closed_gate"
        if base == BASE_BOUNDARY:
            return "boundary"
    return "blocked"


def _normalize_base_kind(v) -> str:
    """
    Map mixed schema 'base' values (ints/strings) to a canonical kind:
      open|terrain|0  -> "open"
      boundary|None   -> "boundary"
      ice|1           -> "ice"
      force|2         -> "force"
      gate|3          -> "gate"
      unknown         -> "boundary" (conservative)
    """
    if isinstance(v, int):
        return {0: "open", 1: "ice", 2: "force", 3: "gate"}.get(v, "boundary")
    if isinstance(v, str):
        s = v.strip().lower()
        return {
            "open": "open",
            "terrain": "open",
            "boundary": "boundary",
            "ice": "ice",
            "force": "force",
            "ion": "force",
            "gate": "gate",
        }.get(s, "boundary")
    return "boundary"


def _gate_state_norm(v) -> int:
    """
    Normalize gate_state to 0:open, 1:closed, 2:locked (conservative default=2 if ambiguous when base == gate).
    Accepts ints or strings ('open'/'closed'/'locked').
    """
    if isinstance(v, int):
        return v if v in (0, 1, 2) else 2
    if isinstance(v, str):
        s = v.strip().lower()
        if s == "open":
            return 0
        if s == "closed":
            return 1
        if s == "locked":
            return 2
        return 2
    return 2


_DELTA = {"n": (0, 1), "s": (0, -1), "e": (1, 0), "w": (-1, 0)}
_OPP = {"n": "s", "s": "n", "e": "w", "w": "e"}


def resolve(world, dynamics, year: int, x: int, y: int, dir_key: str, actor: Optional[Dict] = None) -> EdgeDecision:
    """
    Compute final passability+descriptor for edge (year,x,y,dir_key) by composing BOTH sides:
    current tile's `dir_key` edge AND neighbor tile's opposite edge (bounds-checked).
    Conservative defaults: missing/unknown ⇒ boundary/blocked.
    """
    dk = dir_key.lower()
    dx, dy = _DELTA.get(dk, (0, 0))
    opp = _OPP.get(dk, dk)
    du = dk.upper()
    opp_u = opp.upper()
    reasons: List[Tuple[str, str]] = []

    def _get_tile(_x, _y):
        try:
            if hasattr(world, "get_tile"):
                try:
                    return world.get_tile(year, _x, _y)  # type: ignore[arg-type]
                except TypeError:
                    return world.get_tile(_x, _y)  # type: ignore[arg-type]
            if hasattr(world, "tile"):
                try:
                    return world.tile(year, _x, _y)
                except TypeError:
                    return world.tile(_x, _y)
        except Exception:
            return None
        return None

    cur_tile = _get_tile(x, y) or {}
    nbr_tile = _get_tile(x + dx, y + dy) or {}
    cur_edges = (cur_tile.get("edges") or {}) if isinstance(cur_tile, dict) else {}
    nbr_edges = (nbr_tile.get("edges") or {}) if isinstance(nbr_tile, dict) else {}
    cur_edge = (cur_edges.get(du) or {}) if isinstance(cur_edges, dict) else {}
    nbr_edge = (nbr_edges.get(opp_u) or {}) if isinstance(nbr_edges, dict) else {}

    cur_kind = _normalize_base_kind(cur_edge.get("base", None))
    nbr_kind = _normalize_base_kind(nbr_edge.get("base", None))
    cur_gs = _gate_state_norm(cur_edge.get("gate_state", GATE_OPEN))
    nbr_gs = _gate_state_norm(nbr_edge.get("gate_state", GATE_OPEN))

    reasons.append(("cur.base", cur_kind))
    reasons.append(("nbr.base", nbr_kind))
    if cur_kind == "gate":
        reasons.append(("cur.gate", "open" if cur_gs == 0 else "closed" if cur_gs == 1 else "locked"))
    if nbr_kind == "gate":
        reasons.append(("nbr.gate", "open" if nbr_gs == 0 else "closed" if nbr_gs == 1 else "locked"))

    cur_overlay = None
    try:
        if dynamics is not None and hasattr(dynamics, "overlay_for"):
            cur_overlay = dynamics.overlay_for(year, x, y, du, now=int(time.time()))
            if cur_overlay:
                kind = cur_overlay.get("kind")
                if kind == "barrier":
                    reasons.append(("overlay", f"barrier:{'hard' if cur_overlay.get('hard') else 'blastable'}"))
                    cur_kind = "force" if cur_overlay.get("hard") else "ice"
                elif kind == "blasted":
                    reasons.append(("overlay", "blasted"))
                    cur_kind = "open"
    except Exception:
        pass

    if cur_kind == "boundary" or nbr_kind == "boundary":
        return EdgeDecision(False, DESC_FORCE, reasons, cur_edge, nbr_edge, reason="boundary")
    if (cur_kind == "gate" and cur_gs != 0) or (nbr_kind == "gate" and nbr_gs != 0):
        return EdgeDecision(False, DESC_GATE_CLOSED, reasons, cur_edge, nbr_edge, reason="closed_gate")
    if cur_kind == "ice" or nbr_kind == "ice":
        return EdgeDecision(False, DESC_ICE, reasons, cur_edge, nbr_edge, reason="ice")
    if cur_kind == "force" or nbr_kind == "force":
        return EdgeDecision(False, DESC_FORCE, reasons, cur_edge, nbr_edge, reason="force")
    if (cur_kind == "gate" and cur_gs == 0) or (nbr_kind == "gate" and nbr_gs == 0):
        return EdgeDecision(True, DESC_GATE_OPEN, reasons, cur_edge, nbr_edge, reason="ok")
    return EdgeDecision(True, DESC_AREA, reasons, cur_edge, nbr_edge, reason="ok")

