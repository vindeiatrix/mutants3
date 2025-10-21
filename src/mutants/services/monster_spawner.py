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

import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from mutants.engine import edge_resolver
from mutants.registries import monsters_instances as mon_instances
from mutants.registries import items_instances as itemsreg
from mutants.registries import monsters_catalog
from mutants.registries import dynamics as dynamics_registry
from mutants.services import player_state as pstate
from mutants.services import random_pool
from mutants.services.monster_entities import DEFAULT_INNATE_ATTACK_LINE


LOG = logging.getLogger(__name__)
LOG_P = logging.getLogger("mutants.playersdbg")


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
    line_raw = payload.get("line") if isinstance(payload, Mapping) else None
    line = str(line_raw).strip() if isinstance(line_raw, str) and line_raw.strip() else DEFAULT_INNATE_ATTACK_LINE
    return {
        "name": str(payload.get("name", default_name)),
        "power_base": int(payload.get("power_base", 0) or 0),
        "power_per_level": int(payload.get("power_per_level", 0) or 0),
        "line": line,
    }


def _mint_item_instance_id(template: Mapping[str, Any], item: Mapping[str, Any]) -> str:
    return itemsreg.mint_iid()


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
        origin_raw = raw.get("origin")
        if isinstance(origin_raw, str) and origin_raw.strip():
            entry["origin"] = origin_raw.strip().lower()
        else:
            entry["origin"] = "native"
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
            origin_raw = armour.get("origin") if isinstance(armour, Mapping) else None
            if isinstance(origin_raw, str) and origin_raw.strip():
                entry["origin"] = origin_raw.strip().lower()
            else:
                entry["origin"] = "native"
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


def _clone_template(
    template: Mapping[str, Any],
    pos: Pos,
    *,
    instances: mon_instances.MonstersInstances,
) -> Dict[str, Any]:
    inventory, armour_iid = _clone_inventory(template)
    monster_id_raw = template.get("monster_id") or template.get("id")
    monster_id = str(monster_id_raw or "monster")
    return {
        "instance_id": instances.mint_instance_id(monster_id),
        "monster_id": monster_id,
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
        "ready_target": None,
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
        self._dirty_years: set[int] = set()
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

    def _resolve_year(
        self,
        payload: Mapping[str, Any] | None = None,
        *,
        pos: Iterable[Any] | None = None,
        year: int | None = None,
    ) -> int | None:
        if year is not None:
            try:
                return int(year)
            except (TypeError, ValueError):
                return None

        candidate_pos: Iterable[Any] | None = pos
        if candidate_pos is None and isinstance(payload, Mapping):
            raw_pos = payload.get("pos")
            if raw_pos is None and isinstance(payload.get("monster"), Mapping):
                raw_pos = payload["monster"].get("pos")
            if raw_pos is None and isinstance(payload.get("summary"), Mapping):
                raw_pos = payload["summary"].get("pos")
            candidate_pos = raw_pos  # type: ignore[assignment]

        if isinstance(candidate_pos, Mapping):
            candidate_pos = candidate_pos.get("pos")  # type: ignore[assignment]

        if isinstance(candidate_pos, Iterable):
            parts = list(candidate_pos)
            if parts:
                try:
                    return int(parts[0])
                except (TypeError, ValueError):
                    return None

        if isinstance(payload, Mapping):
            for key in ("year", "world_year"):
                if payload.get(key) is None:
                    continue
                try:
                    return int(payload.get(key))
                except (TypeError, ValueError):
                    continue
        return None

    def notify_monster_death(
        self,
        payload: Mapping[str, Any] | None = None,
        *,
        pos: Iterable[Any] | None = None,
        year: int | None = None,
    ) -> None:
        """Record a monster death and mark the owning year dirty."""

        resolved_year = self._resolve_year(payload, pos=pos, year=year)
        if resolved_year is None:
            LOG.debug("Monster death notification missing year; ignoring")
            return

        now = self._time()
        year_state = self._years.get(resolved_year)
        if year_state is not None:
            if year_state.next_spawn_at <= 0 or year_state.next_spawn_at > now:
                year_state.next_spawn_at = now
        self._dirty_years.add(resolved_year)
        LOG.info(
            "Monster death recorded for year %s; respawn stub queued",
            resolved_year,
        )

    def pending_respawn_years(self) -> frozenset[int]:
        """Return the set of years awaiting a respawn tick."""

        return frozenset(self._dirty_years)

    # ------------------------------------------------------------------
    def tick(self) -> None:
        now = self._time()
        for year, year_state in self._years.items():
            if self._floor <= 0:
                continue
            if self._count_live(year) >= self._floor:
                self._dirty_years.discard(year)
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
        instance = _clone_template(template, pos, instances=self._instances)
        self._instances._add(instance)
        if pstate._pdbg_enabled():  # pragma: no cover - diagnostic logging
            try:
                pstate._pdbg_setup_file_logging()
                hp = instance.get("hp")
                hp_summary = "?/?"
                if isinstance(hp, Mapping):
                    cur = hp.get("current")
                    cap = hp.get("max")
                    hp_summary = f"{cur}/{cap}"
                inv_count = 0
                inventory = instance.get("inventory")
                if isinstance(inventory, list):
                    for entry in inventory:
                        if isinstance(entry, Mapping):
                            inv_count += 1
                LOG_P.info(
                    "[playersdbg] MON-SPAWN id=%s kind=%s pos=%s lvl=%s hp=%s inv=%s armour=%s",
                    instance.get("instance_id"),
                    instance.get("monster_id"),
                    instance.get("pos"),
                    instance.get("level"),
                    hp_summary,
                    inv_count,
                    instance.get("armour_wearing") or "-",
                )
            except Exception:
                pass
        self._instances.save()
        self._schedule_next(year_state, now)
        self._dirty_years.discard(year)


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


@dataclass
class _RuntimeYearStateV2:
    templates: List[Mapping[str, Any]]
    tiles: List[Tuple[int, int, int]]
    next_turn_due: int = 0


class RuntimeMonsterSpawner:
    """Authoritative runtime monster spawner using deterministic RNG."""

    _TILE_CAP_DEFAULT = 4
    _RESAMPLE_LIMIT = 20

    def __init__(
        self,
        *,
        instances: mon_instances.MonstersInstances,
        world_loader: WorldLoader,
        template_resolver: Callable[[int], Sequence[Mapping[str, Any]]],
        years: Iterable[int],
        monsters_state_obj: Optional[Any] = None,
        interval: int = 7,
        jitter_pct: int = 20,
        floor: int = 30,
        cap: int = 60,
        batch_max: int = 5,
        tile_cap: Optional[int] = None,
        rng_name: str = "spawner",
    ) -> None:
        self._instances = instances
        self._world_loader = world_loader
        self._template_resolver = template_resolver
        self._monsters_state = monsters_state_obj
        self._interval = max(1, int(interval))
        self._jitter_pct = max(0, int(jitter_pct))
        self._floor = max(0, int(floor))
        self._cap = max(self._floor, int(cap))
        self._batch_max = max(1, int(batch_max))
        self._tile_cap = self._TILE_CAP_DEFAULT if tile_cap is None else max(0, int(tile_cap))
        self._rng_name = rng_name

        self._turn = 0
        self._template_cache: Dict[int, List[Mapping[str, Any]]] = {}
        self._years: Dict[int, _RuntimeYearStateV2] = {}
        self._active_years: set[int] = {int(year) for year in years}
        self._live_cache: Dict[int, int] = {}

    # ------------------------------------------------------------------
    def _rng(self) -> random.Random:
        random_pool.advance_rng_tick(self._rng_name)
        return random_pool.get_rng(self._rng_name)

    def _next_interval(self, rng: random.Random) -> int:
        base = self._interval
        if self._jitter_pct <= 0:
            return base
        spread = int(round(base * self._jitter_pct / 100.0))
        if spread <= 0:
            return base
        delta = rng.randint(-spread, spread)
        return max(1, base + delta)

    def _resolve_templates(self, year: int) -> List[Mapping[str, Any]]:
        cached = self._template_cache.get(year)
        if cached is not None:
            return cached

        try:
            candidates = self._template_resolver(int(year))
        except Exception:
            candidates = []

        resolved: List[Mapping[str, Any]] = []
        for template in candidates or []:
            if not isinstance(template, Mapping):
                continue
            if template.get("spawnable") is False:
                continue
            resolved.append(dict(template))

        self._template_cache[year] = resolved
        return resolved

    def _collect_tiles(self, year: int) -> List[Tuple[int, int, int]]:
        try:
            world = self._world_loader(int(year))
        except Exception:
            return []

        tiles: List[Tuple[int, int, int]] = []
        iterator = getattr(world, "iter_tiles", None)
        if not callable(iterator):
            return tiles

        for tile in iterator():
            pos = _normalize_pos(tile)
            if pos is None or int(pos[0]) != int(year):
                continue
            x, y = int(pos[1]), int(pos[2])
            if not self._tile_passable_with_world(world, int(year), x, y):
                continue
            tiles.append((int(year), x, y))
        return tiles

    def _tile_passable_with_world(self, world: Any, year: int, x: int, y: int) -> bool:
        try:
            tile = world.get_tile(x, y)
        except Exception:
            tile = None
        if isinstance(tile, Mapping) and tile.get("area_locked"):
            return False
        for dir_code in ("N", "S", "E", "W"):
            try:
                decision = edge_resolver.resolve(
                    world, dynamics_registry, int(year), int(x), int(y), dir_code, actor=None
                )
            except Exception:
                continue
            if getattr(decision, "passable", False):
                return True
        return False

    def _tile_still_passable(self, year: int, x: int, y: int) -> bool:
        try:
            world = self._world_loader(int(year))
        except Exception:
            return False
        return self._tile_passable_with_world(world, int(year), int(x), int(y))

    def _ensure_year_state(self, year: int) -> Optional[_RuntimeYearStateV2]:
        state = self._years.get(year)
        if state is not None:
            if state.tiles and state.templates:
                return state
            return None

        templates = self._resolve_templates(year)
        if not templates:
            return None

        tiles = self._collect_tiles(year)
        if not tiles:
            return None

        state = _RuntimeYearStateV2(templates=templates, tiles=tiles)
        self._years[year] = state
        return state

    def _tile_available(self, pos: Tuple[int, int, int], *, bypass_cap: bool) -> bool:
        year, x, y = (int(pos[0]), int(pos[1]), int(pos[2]))
        if not self._tile_still_passable(year, x, y):
            return False
        if bypass_cap or self._tile_cap <= 0:
            return True
        return self._count_alive_on_tile(year, x, y) < self._tile_cap

    def _count_alive_on_tile(self, year: int, x: int, y: int) -> int:
        total = 0
        for monster in self._instances.list_at(year, x, y):
            if self._is_alive(monster):
                total += 1
        return total

    def _count_live_monsters(self, year: int) -> int:
        cached = self._live_cache.get(year)
        if cached is not None:
            return cached

        total = self._instances.count_alive(year)
        self._live_cache[year] = total
        return total

    def _choose_template(
        self, state: _RuntimeYearStateV2, rng: random.Random
    ) -> Optional[Mapping[str, Any]]:
        if not state.templates:
            return None
        idx = rng.randrange(len(state.templates))
        return dict(state.templates[idx])

    def _choose_tile(
        self, year: int, state: _RuntimeYearStateV2, rng: random.Random
    ) -> Optional[Tuple[int, int, int]]:
        if not state.tiles:
            return None
        attempts = min(len(state.tiles), self._RESAMPLE_LIMIT)
        for _ in range(attempts):
            idx = rng.randrange(len(state.tiles))
            pos = state.tiles[idx]
            if not self._tile_available(pos, bypass_cap=False):
                if not self._tile_still_passable(pos[0], pos[1], pos[2]):
                    state.tiles.pop(idx)
                continue
            return pos
        return None

    def _spawn_from_template(
        self,
        template: Mapping[str, Any],
        pos: Tuple[int, int, int],
        *,
        rng: random.Random,
        bypass_cap: bool,
    ) -> Optional[Dict[str, Any]]:
        year, x, y = (int(pos[0]), int(pos[1]), int(pos[2]))
        if not self._tile_available((year, x, y), bypass_cap=bypass_cap):
            return None

        payload = self._instances.create_instance(template, (year, x, y), rng=rng)
        monster_kind = payload.get("monster_id")
        instance_id = payload.get("instance_id")
        LOG.debug(
            "runtime spawn attempt year=%s x=%s y=%s monster=%s iid=%s",
            year,
            x,
            y,
            monster_kind,
            instance_id,
        )
        try:
            stored = self._instances.spawn(payload)
        except KeyError:
            original_id = str(instance_id)
            retry_id = self._instances.remint_instance_id(payload)
            LOG.warning(
                "runtime spawn duplicate year=%s x=%s y=%s monster=%s iid=%s retry=new_id=%s",
                year,
                x,
                y,
                monster_kind,
                original_id,
                retry_id,
            )
            try:
                stored = self._instances.spawn(payload)
            except KeyError:
                LOG.warning(
                    "runtime spawn duplicate year=%s x=%s y=%s monster=%s iid=%s retry_failed=1",
                    year,
                    x,
                    y,
                    monster_kind,
                    retry_id,
                )
                return None
            else:
                LOG.warning(
                    "runtime spawn duplicate year=%s x=%s y=%s monster=%s iid=%s retry_success=1",
                    year,
                    x,
                    y,
                    monster_kind,
                    retry_id,
                )
        self._live_cache.pop(year, None)
        if self._monsters_state is not None:
            try:
                self._monsters_state.mark_dirty()
            except Exception:
                pass
        return stored

    # ------------------------------------------------------------------
    def tick(self) -> None:
        if self._floor <= 0 or not self._active_years:
            return

        self._turn += 1
        for year in sorted(self._active_years):
            state = self._ensure_year_state(year)
            if state is None:
                continue
            live = self._count_live_monsters(year)
            if live >= self._cap:
                state.next_turn_due = self._turn + self._next_interval(self._rng())
                continue
            if live >= self._floor:
                state.next_turn_due = max(state.next_turn_due, self._turn + self._next_interval(self._rng()))
                continue
            if self._turn < state.next_turn_due:
                continue
            self._spawn_for_year(year, state, live)

    def _spawn_for_year(self, year: int, state: _RuntimeYearStateV2, live: int) -> None:
        remaining_to_floor = max(0, self._floor - live)
        remaining_to_cap = max(0, self._cap - live)
        goal = max(0, min(remaining_to_floor, self._batch_max, remaining_to_cap))
        LOG.info(
            "runtime spawner tick start year=%s live_before=%s floor=%s cap=%s batch_planned=%s",
            year,
            live,
            self._floor,
            self._cap,
            goal,
        )
        spawned = 0
        for _ in range(goal):
            rng = self._rng()
            pos = self._choose_tile(year, state, rng)
            if pos is None:
                break
            template = self._choose_template(state, rng)
            if template is None:
                break
            record = self._spawn_from_template(template, pos, rng=rng, bypass_cap=False)
            if record is None:
                continue
            spawned += 1

        state.next_turn_due = self._turn + self._next_interval(self._rng())
        if spawned:
            self._live_cache.pop(year, None)
            live_after = self._count_live_monsters(year)
        else:
            live_after = live
        LOG.info(
            "runtime spawner tick end year=%s live_before=%s batch_planned=%s batch_done=%s live_after=%s",
            year,
            live,
            goal,
            spawned,
            live_after,
        )

    def notify_monster_death(
        self,
        payload: Mapping[str, Any] | None = None,
        *,
        pos: Iterable[Any] | None = None,
        year: int | None = None,
    ) -> None:
        resolved = _resolve_year(payload, pos=pos, year=year)
        if resolved is None:
            return
        self._live_cache.pop(resolved, None)
        state = self._years.get(resolved)
        if state is not None and state.next_turn_due > self._turn:
            state.next_turn_due = self._turn
        self._active_years.add(resolved)

    def spawn_template(
        self,
        template: Mapping[str, Any],
        pos: Tuple[int, int, int],
        *,
        bypass_cap: bool = False,
    ) -> Optional[Dict[str, Any]]:
        year = int(pos[0])
        self._active_years.add(year)
        rng = self._rng()
        return self._spawn_from_template(dict(template), (year, int(pos[1]), int(pos[2])), rng=rng, bypass_cap=bypass_cap)

    @staticmethod
    def _is_alive(monster: Mapping[str, Any]) -> bool:
        hp = monster.get("hp") if isinstance(monster, Mapping) else None
        if isinstance(hp, Mapping):
            try:
                return int(hp.get("current", 0)) > 0
            except (TypeError, ValueError):
                return True
        return True


def build_runtime_spawner(
    *,
    templates_state: Optional[Any],
    catalog: Optional[monsters_catalog.MonstersCatalog],
    instances: mon_instances.MonstersInstances,
    world_loader: WorldLoader,
    years: Iterable[int],
    monsters_state_obj: Optional[Any] = None,
    config: Optional[Mapping[str, int]] = None,
    tile_cap: int = RuntimeMonsterSpawner._TILE_CAP_DEFAULT,
) -> RuntimeMonsterSpawner:
    template_index: Dict[int, List[Dict[str, Any]]] = {}

    if templates_state is not None:
        if hasattr(templates_state, "list_all"):
            source = templates_state.list_all()
        else:
            source = templates_state
        for entry in source or []:
            if not isinstance(entry, Mapping):
                continue
            if entry.get("spawnable") is False:
                continue
            years_raw = entry.get("pinned_years") or entry.get("spawn_years") or []
            if not isinstance(years_raw, Iterable):
                years_raw = [years_raw]
            for value in years_raw:
                try:
                    year = int(value)
                except (TypeError, ValueError):
                    continue
                template_index.setdefault(year, []).append(dict(entry))

    def _resolver(target_year: int) -> Sequence[Mapping[str, Any]]:
        pinned = template_index.get(int(target_year))
        if pinned:
            return [dict(entry) for entry in pinned]
        if catalog is not None:
            try:
                return [dict(entry) for entry in catalog.list_spawnable(int(target_year))]
            except Exception:
                return []
        return []

    cfg = dict(config or {})
    interval = int(cfg.get("interval", 7))
    jitter = int(cfg.get("jitter_pct", 20))
    floor = int(cfg.get("floor", 30))
    cap = int(cfg.get("cap", 60))
    batch = int(cfg.get("batch_max", 5))

    candidate_years: set[int] = {int(year) for year in years}
    candidate_years.update(template_index.keys())

    return RuntimeMonsterSpawner(
        instances=instances,
        world_loader=world_loader,
        template_resolver=_resolver,
        years=candidate_years,
        monsters_state_obj=monsters_state_obj,
        interval=interval,
        jitter_pct=jitter,
        floor=floor,
        cap=cap,
        batch_max=batch,
        tile_cap=tile_cap,
    )

