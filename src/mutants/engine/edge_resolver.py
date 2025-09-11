from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import time

from mutants.registries import world as W

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


def _base_to_descriptor(base: int) -> Tuple[bool, str, str]:
    if base == W.BASE_OPEN:
        return True, DESC_AREA, "base:open"
    if base == W.BASE_TERRAIN:
        return False, DESC_ICE, "base:terrain"
    if base == W.BASE_BOUNDARY:
        return False, DESC_FORCE, "base:boundary"
    if base == W.BASE_GATE:
        return True, DESC_GATE_OPEN, "base:gate"
    return False, DESC_FORCE, f"base:unknown({base})"


def _gate_state_to_descriptor(gate_state: int) -> Tuple[Optional[bool], str, str]:
    if gate_state == W.GATE_OPEN:
        return True, DESC_GATE_OPEN, "gate:open"
    if gate_state == W.GATE_CLOSED:
        return False, DESC_GATE_CLOSED, "gate:closed"
    if gate_state == W.GATE_LOCKED:
        return False, DESC_GATE_CLOSED, "gate:locked"
    return None, "", "gate:none"


def resolve(world, dynamics, year: int, x: int, y: int, dir_key: str, actor: Optional[Dict] = None) -> EdgeDecision:
    reasons: List[Tuple[str, str]] = []

    edge: Dict = {}
    try:
        tile = world.get_tile(x, y)
        if tile:
            edge = tile.get("edges", {}).get(dir_key, {}) or {}
    except Exception:
        edge = {}

    base_code = int(edge.get("base", W.BASE_BOUNDARY))
    passable, desc, bref = _base_to_descriptor(base_code)
    reasons.append(("base", bref))

    if base_code == W.BASE_GATE:
        gate_state = int(edge.get("gate_state", W.GATE_OPEN))
        gs = _gate_state_to_descriptor(gate_state)
        if gs[0] is not None:
            passable, desc = bool(gs[0]), gs[1]
            reasons.append(("gate", gs[2]))

    # Static spell blocks
    spell_block = int(edge.get("spell_block", 0))
    if spell_block == 1:
        passable = False
        desc = DESC_ICE
        reasons.append(("spell", "spell:ice"))
    elif spell_block == 2:
        passable = False
        desc = DESC_FORCE
        reasons.append(("spell", "spell:ion"))

    # Dynamic overlays
    try:
        if dynamics is not None and hasattr(dynamics, "overlay_for"):
            ov = dynamics.overlay_for(year, x, y, dir_key, now=int(time.time()))
            if ov:
                kind = ov.get("kind")
                if kind == "barrier":
                    hard = bool(ov.get("hard", False))
                    passable = False
                    desc = DESC_FORCE if hard else DESC_ICE
                    reasons.append(("overlay", f"barrier:{'hard' if hard else 'blastable'}"))
                elif kind == "blasted":
                    passable = True
                    desc = DESC_AREA
                    reasons.append(("overlay", "blasted"))
    except Exception:
        pass

    if actor:
        rod = actor.get("has_passage_rod")
        if rod and any(r[0] == "overlay" and r[1].startswith("barrier:blastable") for r in reasons):
            passable = True
            desc = DESC_AREA
            reasons.append(("actor", "passage_rod"))

    desc = desc if desc in CANON else (DESC_AREA if passable else DESC_FORCE)
    return EdgeDecision(passable=passable, descriptor=desc, reason_chain=reasons)
