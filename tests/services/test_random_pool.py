from __future__ import annotations

import random

import pytest

from mutants.services.random_pool import RandomPool


class InMemoryRuntimeKV:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


def _sample(rng: random.Random, size: int = 3) -> list[float]:
    return [rng.random() for _ in range(size)]


def test_random_pool_reproducible_across_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUTANTS_RNG_SEED", "0x2A")
    store = InMemoryRuntimeKV()

    pool_first = RandomPool(store)
    baseline = _sample(pool_first.get_rng("combat"))
    assert baseline == _sample(pool_first.get_rng("combat"))

    # Persisted state should survive a new pool instance.
    pool_second = RandomPool(store)
    assert baseline == _sample(pool_second.get_rng("combat"))
    assert pool_second.get_tick("combat") == 0

    # Advancing a tick changes the sequence deterministically.
    new_tick = pool_second.advance_tick("combat")
    assert new_tick == 1
    advanced = _sample(pool_second.get_rng("combat"))
    assert advanced != baseline

    # A fresh pool sees the persisted tick and reproduces the advanced sequence.
    pool_third = RandomPool(store)
    assert pool_third.get_tick("combat") == 1
    assert advanced == _sample(pool_third.get_rng("combat"))


def test_random_pool_rejects_negative_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUTANTS_RNG_SEED", "42")
    pool = RandomPool(InMemoryRuntimeKV())

    with pytest.raises(ValueError):
        pool.advance_tick("combat", steps=-1)
