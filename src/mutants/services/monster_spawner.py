"""Runtime monster spawner.

This module implements the authoritative, tick-driven monster spawner that
maintains a per-year population floor. The spawner is intentionally stateless
across process runs; the SQLite-backed ``MonstersInstances`` registry is the
source of truth for population counts, and world geometry is consulted on
demand via the world loader.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from mutants.engine import edge_resolver
from mutants.registries import monsters_instances as mon_instances
from mutants.registries import monsters_catalog
from mutants.registries import dynamics as dynamics_registry
from mutants.services import random_pool


LOG = logging.getLogger(__name__)


Year = int
Pos = List[int]


class _WorldYearProtocol:
    """Lightweight protocol for the world registry used by the spawner."""

    def iter_tiles(self) -> Iterable[Mapping[str, Any]]:  # pragma: no cover - protocol
        raise NotImplementedError


WorldLoader = Callable[[int], _WorldYearProtocol]


def _normalize_pos(tile: Mapping[str, Any]) -> Pos | None:
    pos = tile.get("pos")
    if not (isinstance(pos, list) and len(pos) == 3):
        return None
    try:
        year, x, y = (int(pos[0]), int(pos[1]), int(pos[2]))
    except (TypeError, ValueError):
        return None
    return [year, x, y]


@dataclass
class _RuntimeYearState:
    templates: List[Mapping[str, Any]]
    next_turn_due: int = 0
    last_tick_processed: int = -1


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
        self._years: Dict[int, _RuntimeYearState] = {}
        self._active_years: set[int] = {int(year) for year in years}
        self._tile_index: Dict[int, List[Tuple[int, int]]] = {}
        self._last_turn_tick: Optional[int] = None

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

    def _build_tile_index(self, year: int) -> List[Tuple[int, int]]:
        try:
            world = self._world_loader(int(year))
        except Exception:
            return []

        tiles: List[Tuple[int, int]] = []
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
            tiles.append((x, y))
        return tiles

    def _tile_index_for_year(self, year: int) -> List[Tuple[int, int]]:
        cached = self._tile_index.get(year)
        if cached is not None:
            return cached
        tiles = self._build_tile_index(year)
        self._tile_index[year] = tiles
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

    def _ensure_year_state(self, year: int) -> Optional[_RuntimeYearState]:
        state = self._years.get(year)
        if state is not None:
            if state.templates and self._tile_index_for_year(year):
                return state
            return None

        templates = self._resolve_templates(year)
        if not templates:
            return None

        tiles = self._tile_index_for_year(year)
        if not tiles:
            return None

        state = _RuntimeYearState(templates=templates)
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
        try:
            return int(self._instances.count_alive(year))
        except Exception:
            LOG.warning("runtime spawner failed to count monsters for year=%s", year)
            return 0

    def _choose_template(
        self, state: _RuntimeYearState, rng: random.Random
    ) -> Optional[Mapping[str, Any]]:
        if not state.templates:
            return None
        idx = rng.randrange(len(state.templates))
        return dict(state.templates[idx])

    def _choose_tile(
        self, year: int, state: _RuntimeYearState, rng: random.Random
    ) -> Optional[Tuple[int, int, int]]:
        tiles = self._tile_index_for_year(year)
        if not tiles:
            return None
        attempts = min(len(tiles), self._RESAMPLE_LIMIT)
        for _ in range(attempts):
            idx = rng.randrange(len(tiles))
            x, y = tiles[idx]
            pos = (int(year), int(x), int(y))
            if not self._tile_available(pos, bypass_cap=False):
                if not self._tile_still_passable(year, x, y):
                    tiles.pop(idx)
                continue
            return pos
        LOG.warning(
            "runtime spawn tile selection exhausted year=%s attempts=%s pool=%s",
            year,
            attempts,
            len(tiles),
        )
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

        try:
            current_turn_tick = random_pool.get_rng_tick("turn")
        except Exception:
            current_turn_tick = None
        if current_turn_tick == self._last_turn_tick:
            return
        self._last_turn_tick = current_turn_tick

        current_turn = self._turn
        for year in sorted(self._active_years):
            state = self._ensure_year_state(year)
            if state is None:
                continue
            if state.last_tick_processed == current_turn:
                continue
            live = self._count_live_monsters(year)
            if live >= self._cap:
                state.next_turn_due = current_turn + self._next_interval(self._rng())
                continue
            if live >= self._floor:
                state.next_turn_due = max(
                    state.next_turn_due, current_turn + self._next_interval(self._rng())
                )
                continue
            if current_turn < state.next_turn_due:
                continue
            self._spawn_for_year(year, state, live, current_turn)

        self._turn = current_turn + 1

    def _spawn_for_year(
        self, year: int, state: _RuntimeYearState, live: int, current_turn: int
    ) -> None:
        remaining_to_floor = max(0, self._floor - live)
        remaining_to_cap = max(0, self._cap - live)
        goal = max(0, min(remaining_to_floor, self._batch_max, remaining_to_cap))
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

        state.next_turn_due = current_turn + self._next_interval(self._rng())
        state.last_tick_processed = current_turn
        live_after = live if spawned == 0 else self._count_live_monsters(year)
        LOG.info(
            "runtime spawner tick year=%s live_before=%s floor=%s batch_planned=%s batch_spawned=%s live_after=%s",
            year,
            live,
            self._floor,
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
        state = self._years.get(resolved)
        if state is not None:
            if state.next_turn_due > self._turn:
                state.next_turn_due = self._turn
            state.last_tick_processed = -1
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

