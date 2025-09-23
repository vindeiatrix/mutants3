"""Monster spawner controller.

This module manages a lightweight controller that keeps a floor of monsters
per world year.  It operates purely in-memory with the registries already
available in the codebase (world loader, monsters state/instances) and writes
changes back via ``MonstersInstances.save`` after spawning.

Design goals derived from the task description:

* Maintain a per-year population floor (default 30).
* Only spawn at most one monster per year per minute; the actual interval is
  jittered slightly so spawns do not stack on deterministic boundaries.
* Spawned monsters are based on templates that are "pinned" to a specific
  year.  Templates typically come from ``monsters_state`` records imported via
  ``monsters_importer``.

The controller is intentionally stateless between process runs except for the
monsters added to the ``MonstersInstances`` registry.  Each controller keeps
its own notion of the next permissible spawn time per year and respects that
rate limit regardless of how often ``tick`` is invoked.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping

from mutants.registries import monsters_instances as mon_instances


Year = int
Pos = List[int]


class _WorldYearProtocol:
    """Lightweight protocol for the world registry used by the spawner."""

    def iter_tiles(self) -> Iterable[Mapping[str, Any]]:  # pragma: no cover - protocol
        raise NotImplementedError


WorldLoader = Callable[[int], _WorldYearProtocol]


def _coerce_years(payload: Mapping[str, Any]) -> List[int]:
    years: List[int] = []
    raw_years = payload.get("pinned_years")
    if not isinstance(raw_years, Iterable):
        return years
    for entry in raw_years:
        try:
            year = int(entry)
        except (TypeError, ValueError):
            continue
        if year not in years:
            years.append(year)
    return years


def _normalize_pos(tile: Mapping[str, Any]) -> Pos | None:
    pos = tile.get("pos")
    if not (isinstance(pos, list) and len(pos) == 3):
        return None
    try:
        year, x, y = (int(pos[0]), int(pos[1]), int(pos[2]))
    except (TypeError, ValueError):
        return None
    return [year, x, y]


def _default_time() -> float:
    return time.monotonic()


def _copy_innate_attack(template: Mapping[str, Any]) -> Dict[str, Any]:
    payload = template.get("innate_attack")
    default_name = str(template.get("name") or template.get("id") or "Monster")
    if not isinstance(payload, Mapping):
        payload = {}
    return {
        "name": str(payload.get("name", default_name)),
        "power_base": int(payload.get("power_base", 0) or 0),
        "power_per_level": int(payload.get("power_per_level", 0) or 0),
        "message": str(
            payload.get(
                "message",
                f"{{monster}} attacks {{target}}!",
            )
        ),
    }


def _mint_instance_id(template: Mapping[str, Any]) -> str:
    base = str(template.get("id") or template.get("monster_id") or "monster")
    return f"{base}#{uuid.uuid4().hex[:8]}"


def _mint_item_instance_id(template: Mapping[str, Any], item: Mapping[str, Any]) -> str:
    base_mon = str(template.get("id") or template.get("monster_id") or "monster")
    raw_item = item.get("iid") or item.get("item_id") or "item"
    return f"{base_mon}#{raw_item}#{uuid.uuid4().hex[:6]}"


def _clone_inventory(template: Mapping[str, Any]) -> tuple[List[Dict[str, Any]], str | None]:
    bag = template.get("bag")
    inventory: List[Dict[str, Any]] = []
    if not isinstance(bag, Iterable):
        bag = []

    iid_map: Dict[str, str] = {}

    for raw in bag:
        if not isinstance(raw, Mapping):
            continue
        entry: Dict[str, Any] = {}
        item_id = raw.get("item_id")
        if item_id:
            entry["item_id"] = str(item_id)
        qty = raw.get("qty")
        if isinstance(qty, int) and qty > 1:
            entry["qty"] = qty
        minted = _mint_item_instance_id(template, raw)
        entry["instance_id"] = minted
        iid = raw.get("iid")
        if isinstance(iid, str) and iid:
            iid_map[iid] = minted
        inventory.append(entry)
        if len(inventory) >= 4:
            break

    armour = template.get("armour_slot")
    armour_iid: str | None = None
    if isinstance(armour, Mapping):
        ref = armour.get("iid")
        armour_iid = iid_map.get(ref)
        if not armour_iid:
            armour_iid = _mint_item_instance_id(template, armour)
            if isinstance(ref, str) and ref:
                iid_map[ref] = armour_iid
        # ensure armour reference exists in inventory (respecting 4 item cap)
        found = any(entry.get("instance_id") == armour_iid for entry in inventory)
        if not found:
            entry: Dict[str, Any] = {"instance_id": armour_iid}
            if armour.get("item_id"):
                entry["item_id"] = str(armour["item_id"])
            if len(inventory) >= 4:
                # drop the oldest non-armour item to make room
                inventory.pop(0)
            inventory.append(entry)

    return inventory, armour_iid


def _copy_hp(template: Mapping[str, Any]) -> Dict[str, int]:
    hp = template.get("hp")
    if isinstance(hp, Mapping):
        try:
            max_hp = int(hp.get("max", hp.get("current", 1)))
        except (TypeError, ValueError):
            max_hp = 1
    else:
        max_hp = 1
    max_hp = max(1, max_hp)
    return {"current": max_hp, "max": max_hp}


def _derive_armour_class(template: Mapping[str, Any]) -> int:
    derived = template.get("derived")
    if isinstance(derived, Mapping) and derived.get("armour_class") is not None:
        try:
            return int(derived["armour_class"])
        except (TypeError, ValueError):
            pass
    ac = template.get("armour_class")
    try:
        return int(ac)
    except (TypeError, ValueError):
        return 0


def _coerce_positive_int(value: Any, *, default: int = 0) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, result)


def _clone_template(template: Mapping[str, Any], pos: Pos) -> Dict[str, Any]:
    inventory, armour_iid = _clone_inventory(template)
    return {
        "instance_id": _mint_instance_id(template),
        "monster_id": str(template.get("id") or template.get("monster_id") or "monster"),
        "pos": [int(pos[0]), int(pos[1]), int(pos[2])],
        "hp": _copy_hp(template),
        "armour_class": _derive_armour_class(template),
        "level": _coerce_positive_int(template.get("level"), default=1),
        "ions": _coerce_positive_int(template.get("ions"), default=0),
        "riblets": _coerce_positive_int(template.get("riblets"), default=0),
        "inventory": inventory,
        "armour_wearing": armour_iid,
        "readied_spell": None,
        "target_player_id": None,
        "target_monster_id": None,
        "taunt": str(template.get("taunt", "")),
        "innate_attack": _copy_innate_attack(template),
        "spells": [str(s) for s in template.get("spells", []) if isinstance(s, (str, int))],
    }


@dataclass
class _YearState:
    templates: List[Mapping[str, Any]]
    tiles: List[Pos]
    next_spawn_at: float = 0.0


class MonsterSpawnerController:
    """Controller enforcing a per-year monster population floor."""

    def __init__(
        self,
        *,
        templates: Iterable[Mapping[str, Any]],
        instances: mon_instances.MonstersInstances,
        world_loader: WorldLoader,
        rng: random.Random | None = None,
        time_func: Callable[[], float] | None = None,
        floor_per_year: int = 30,
        spawn_interval: float = 60.0,
        spawn_jitter: float = 15.0,
    ) -> None:
        self._rng = rng or random.Random()
        self._time = time_func or _default_time
        self._floor = max(0, int(floor_per_year))
        self._interval = max(1.0, float(spawn_interval))
        self._jitter = max(0.0, float(spawn_jitter))
        self._instances = instances
        self._world_loader = world_loader

        self._years: Dict[int, _YearState] = {}
        self._init_years(templates)

    # ------------------------------------------------------------------
    def _init_years(self, templates: Iterable[Mapping[str, Any]]) -> None:
        staging: Dict[int, List[Mapping[str, Any]]] = {}
        for raw in templates:
            if not isinstance(raw, Mapping):
                continue
            years = _coerce_years(raw)
            if not years:
                continue
            for year in years:
                staging.setdefault(year, []).append(dict(raw))

        for year, templates_for_year in staging.items():
            tiles = self._collect_tiles(year)
            if not tiles or not templates_for_year:
                continue
            self._years[year] = _YearState(templates=list(templates_for_year), tiles=tiles)

    def _collect_tiles(self, year: int) -> List[Pos]:
        try:
            world = self._world_loader(int(year))
        except FileNotFoundError:
            return []
        except Exception:
            return []

        tiles: List[Pos] = []
        for tile in world.iter_tiles():
            pos = _normalize_pos(tile)
            if pos is None:
                continue
            if int(pos[0]) != int(year):
                continue
            tiles.append(pos)
        return tiles

    def _count_live(self, year: int) -> int:
        total = 0
        for inst in self._instances.list_all():
            pos = inst.get("pos") if isinstance(inst, Mapping) else None
            if not (isinstance(pos, list) and len(pos) == 3):
                continue
            try:
                inst_year = int(pos[0])
            except (TypeError, ValueError):
                continue
            if inst_year == int(year):
                total += 1
        return total

    def _schedule_next(self, year_state: _YearState, now: float) -> None:
        delta = self._interval
        if self._jitter:
            delta += self._rng.uniform(-self._jitter, self._jitter)
        delta = max(1.0, delta)
        year_state.next_spawn_at = now + delta

    # ------------------------------------------------------------------
    def tick(self) -> None:
        now = self._time()
        for year, year_state in self._years.items():
            if self._floor <= 0:
                continue
            if self._count_live(year) >= self._floor:
                continue
            if now < year_state.next_spawn_at:
                continue
            self._spawn_for_year(year, year_state, now)

    def _spawn_for_year(self, year: int, year_state: _YearState, now: float) -> None:
        if not year_state.tiles or not year_state.templates:
            self._schedule_next(year_state, now)
            return

        template = self._rng.choice(year_state.templates)
        pos = list(self._rng.choice(year_state.tiles))
        instance = _clone_template(template, pos)
        self._instances._add(instance)
        self._instances.save()
        self._schedule_next(year_state, now)


def build_controller(
    *,
    templates_state,
    instances: mon_instances.MonstersInstances,
    world_loader: WorldLoader,
    rng: random.Random | None = None,
    time_func: Callable[[], float] | None = None,
    floor_per_year: int = 30,
    spawn_interval: float = 60.0,
    spawn_jitter: float = 15.0,
) -> MonsterSpawnerController:
    """Convenience helper to construct a controller from ``MonstersState``."""

    if hasattr(templates_state, "list_all"):
        templates_iter = templates_state.list_all()
    else:
        templates_iter = list(templates_state or [])

    return MonsterSpawnerController(
        templates=templates_iter,
        instances=instances,
        world_loader=world_loader,
        rng=rng,
        time_func=time_func,
        floor_per_year=floor_per_year,
        spawn_interval=spawn_interval,
        spawn_jitter=spawn_jitter,
    )

