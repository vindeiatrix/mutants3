from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Protocol

from mutants.env import get_state_backend as _get_state_backend

from .sqlite_store import get_stores as sqlite_get_stores

__all__ = [
    "ItemsInstanceStore",
    "MonstersInstanceStore",
    "StateStores",
    "get_state_backend",
    "get_stores",
]


class ItemsInstanceStore(Protocol):
    def snapshot(self) -> Iterable[Dict[str, Any]]: ...

    def replace_all(self, records: Iterable[Dict[str, Any]]) -> None: ...

    def get_by_iid(self, iid: str) -> Optional[Dict[str, Any]]: ...

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]: ...

    def list_by_owner(self, owner: str) -> Iterable[Dict[str, Any]]: ...

    def mint(self, rec: Dict[str, Any]) -> None: ...

    def move(self, iid: str, *, year: int, x: int, y: int) -> None: ...

    def update_fields(self, iid: str, **fields: Any) -> None: ...

    def delete(self, iid: str) -> None: ...


class MonstersInstanceStore(Protocol):
    def snapshot(self) -> Iterable[Dict[str, Any]]: ...

    def replace_all(self, records: Iterable[Dict[str, Any]]) -> None: ...

    def get(self, mid: str) -> Optional[Dict[str, Any]]: ...

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]: ...

    def spawn(self, rec: Dict[str, Any]) -> None: ...

    def update_fields(self, mid: str, **fields: Any) -> None: ...

    def delete(self, mid: str) -> None: ...


@dataclass(frozen=True)
class StateStores:
    items: ItemsInstanceStore
    monsters: MonstersInstanceStore


def get_state_backend() -> str:
    return _get_state_backend()


def get_stores() -> StateStores:
    backend = get_state_backend()
    if backend == "sqlite":
        return sqlite_get_stores()
    raise ValueError(f"Unsupported state backend: {backend}")
