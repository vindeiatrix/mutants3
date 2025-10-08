from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Protocol

from mutants.env import get_state_backend as _get_state_backend

__all__ = [
    "ItemsInstanceStore",
    "MonstersInstanceStore",
    "StateStores",
    "get_state_backend",
    "get_stores",
]


class ItemsInstanceStore(Protocol):
    def get_by_iid(self, iid: str) -> Optional[Dict[str, Any]]: ...

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]: ...

    def list_by_owner(self, owner: str) -> Iterable[Dict[str, Any]]: ...

    def mint(self, rec: Dict[str, Any]) -> None: ...

    def move(self, iid: str, *, year: int, x: int, y: int) -> None: ...

    def update_fields(self, iid: str, **fields: Any) -> None: ...

    def delete(self, iid: str) -> None: ...


class MonstersInstanceStore(Protocol):
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


class _JSONItemsInstanceStore:
    __slots__ = ()

    @staticmethod
    def _registry():
        from . import items_instances

        return items_instances

    def get_by_iid(self, iid: str) -> Optional[Dict[str, Any]]:
        registry = self._registry()
        return registry.get_instance(iid)

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        registry = self._registry()
        return list(registry.list_instances_at(year, x, y))

    def list_by_owner(self, owner: str) -> Iterable[Dict[str, Any]]:
        registry = self._registry()
        snapshot = registry.snapshot_instances()
        target = str(owner)
        matches: list[Dict[str, Any]] = []
        for inst in snapshot:
            owner_val = inst.get("owner")
            if isinstance(owner_val, str) and owner_val == target:
                matches.append(inst)
                continue
            meta = inst.get("meta")
            if isinstance(meta, dict):
                meta_owner = meta.get("owner")
                if isinstance(meta_owner, str) and meta_owner == target:
                    matches.append(inst)
        return matches

    def mint(self, rec: Dict[str, Any]) -> None:
        registry = self._registry()
        registry.bulk_add([dict(rec)])

    def move(self, iid: str, *, year: int, x: int, y: int) -> None:
        registry = self._registry()
        registry.move_instance(iid, dest=(year, x, y))

    def update_fields(self, iid: str, **fields: Any) -> None:
        registry = self._registry()
        registry.update_instance(iid, **fields)

    def delete(self, iid: str) -> None:
        registry = self._registry()
        registry.remove_instance(iid)


class _JSONMonstersInstanceStore:
    __slots__ = ()

    @staticmethod
    def _load():
        from . import monsters_instances

        return monsters_instances.load_monsters_instances()

    def get(self, mid: str) -> Optional[Dict[str, Any]]:
        registry = self._load()
        return registry.get(str(mid))

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        registry = self._load()
        return list(registry.list_at(year, x, y))

    def spawn(self, rec: Dict[str, Any]) -> None:
        registry = self._load()
        payload = dict(rec)
        if "instance_id" not in payload:
            raise KeyError("Monsters instances require an 'instance_id' field")
        registry._add(payload)  # type: ignore[attr-defined]
        registry.save()

    def update_fields(self, mid: str, **fields: Any) -> None:
        registry = self._load()
        monster = registry.get(str(mid))
        if monster is None:
            raise KeyError(mid)
        for key, value in fields.items():
            if value is None:
                monster.pop(key, None)
            else:
                monster[key] = value
        registry._dirty = True  # type: ignore[attr-defined]
        registry.save()

    def delete(self, mid: str) -> None:
        registry = self._load()
        sid = str(mid)
        removed = registry._by_id.pop(sid, None)  # type: ignore[attr-defined]
        if removed is None:
            return
        registry._items = [  # type: ignore[attr-defined]
            monster for monster in registry._items  # type: ignore[attr-defined]
            if str(monster.get("instance_id")) != sid
        ]
        registry._dirty = True  # type: ignore[attr-defined]
        registry.save()


def get_stores() -> StateStores:
    backend = get_state_backend()
    if backend == "json":
        return StateStores(
            items=_JSONItemsInstanceStore(),
            monsters=_JSONMonstersInstanceStore(),
        )
    if backend == "sqlite":  # pragma: no cover - placeholder until sqlite backend lands
        from .storage_sqlite import get_stores as sqlite_get_stores  # type: ignore[import]

        return sqlite_get_stores()
    raise ValueError(f"Unsupported state backend: {backend}")
