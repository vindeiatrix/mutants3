"""Typed view-models for the UI renderer."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class EdgeDesc(TypedDict, total=False):
    base: int
    gate_state: Optional[int]
    key_type: Optional[int]


class Coords(TypedDict):
    x: int
    y: int


class Thing(TypedDict, total=False):
    name: str
    id: str


class RoomVM(TypedDict, total=False):
    header: str
    coords: Coords
    dirs: Dict[str, EdgeDesc]
    monsters_here: List[Thing]
    ground_item_ids: List[str]
    has_ground: bool
    events: List[str]
    shadows: List[str]
    flags: Dict[str, Any]
