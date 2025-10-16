from __future__ import annotations

import json
import random
import secrets
from dataclasses import dataclass
from threading import RLock
from typing import Dict, Optional

from mutants.env import get_runtime_seed
from mutants.registries.storage import RuntimeKVStore, get_stores
from mutants.util import derive_seed_value

__all__ = [
    "RandomPool",
    "advance_rng_tick",
    "get_rng",
    "get_rng_tick",
]

_KEY_PREFIX = "rng::"


@dataclass
class _RNGState:
    seed: str
    tick: int

    def as_json(self) -> str:
        return json.dumps({"seed": self.seed, "tick": self.tick}, separators=(",", ":"))


class RandomPool:
    """Registry-backed random number generator pool."""

    def __init__(self, store: RuntimeKVStore, *, default_seed: Optional[str] = None) -> None:
        self._store = store
        self._cache: Dict[str, _RNGState] = {}
        self._lock = RLock()
        self._default_seed = default_seed if default_seed is not None else get_runtime_seed()

    def get_rng(self, name: str) -> random.Random:
        """Return a deterministic ``random.Random`` for *name*."""

        with self._lock:
            state = self._load_state(name)
            seed_value = derive_seed_value(state.seed, name, state.tick)
        return random.Random(seed_value)

    def get_tick(self, name: str) -> int:
        """Return the persisted tick counter for *name*."""

        with self._lock:
            return self._load_state(name).tick

    def advance_tick(self, name: str, *, steps: int = 1) -> int:
        """Advance the tick counter for *name* and return the new value."""

        if steps < 0:
            raise ValueError("steps must be non-negative")
        if steps == 0:
            return self.get_tick(name)

        with self._lock:
            state = self._load_state(name)
            state.tick += steps
            self._persist_state(name, state)
            return state.tick

    def reset_tick(self, name: str) -> None:
        """Reset the tick counter for *name* back to zero."""

        with self._lock:
            state = self._load_state(name)
            if state.tick == 0:
                return
            state.tick = 0
            self._persist_state(name, state)

    # Internal helpers -------------------------------------------------
    def _load_state(self, name: str) -> _RNGState:
        cached = self._cache.get(name)
        if cached is not None:
            return cached

        state = self._read_from_store(name)
        self._cache[name] = state
        return state

    def _read_from_store(self, name: str) -> _RNGState:
        key = self._key(name)
        raw = self._store.get(key)
        if raw is None:
            return self._initialize_state(name)

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        seed = payload.get("seed") if isinstance(payload, dict) else None
        tick = payload.get("tick") if isinstance(payload, dict) else None

        needs_persist = False
        if not isinstance(seed, str) or not seed:
            seed = self._generate_seed()
            needs_persist = True
        if not isinstance(tick, int):
            try:
                tick = int(tick)
            except (TypeError, ValueError):
                tick = 0
                needs_persist = True

        state = _RNGState(seed=seed, tick=tick)
        if needs_persist:
            self._persist_state(name, state)
        return state

    def _initialize_state(self, name: str) -> _RNGState:
        state = _RNGState(seed=self._generate_seed(), tick=0)
        self._persist_state(name, state)
        return state

    def _persist_state(self, name: str, state: _RNGState) -> None:
        self._cache[name] = state
        self._store.set(self._key(name), state.as_json())

    def _generate_seed(self) -> str:
        return self._default_seed or secrets.token_hex(16)

    @staticmethod
    def _key(name: str) -> str:
        return f"{_KEY_PREFIX}{name}"


_POOL: Optional[RandomPool] = None
_POOL_LOCK = RLock()


def _get_pool() -> RandomPool:
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = RandomPool(get_stores().runtime_kv)
    return _POOL


def get_rng(name: str) -> random.Random:
    """Return a RNG instance for *name* using the process-wide pool."""

    return _get_pool().get_rng(name)


def advance_rng_tick(name: str, *, steps: int = 1) -> int:
    """Advance the tick counter for *name* using the process-wide pool."""

    return _get_pool().advance_tick(name, steps=steps)


def get_rng_tick(name: str) -> int:
    """Return the stored tick counter for *name* using the shared pool."""

    return _get_pool().get_tick(name)
