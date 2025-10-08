from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from mutants.io.atomic import atomic_write_json
from mutants.state import state_path

__all__ = [
    "JSONItemsInstanceStore",
    "JSONMonstersInstanceStore",
]


class JSONItemsInstanceStore:
    """JSON-backed implementation of :class:`ItemsInstanceStore`."""

    __slots__ = ()

    _LOG = logging.getLogger("mutants.itemsdbg")

    @staticmethod
    def _helpers():
        from . import items_instances as registry

        return (
            registry._detect_duplicate_iids,
            registry._handle_duplicates,
            registry._normalize_instance,
            registry._normalize_instances,
            registry._pos_of,
            registry._instance_id,
        )

    @staticmethod
    def _default_path() -> Path:
        from . import items_instances as registry

        value = getattr(registry, "DEFAULT_INSTANCES_PATH", None)
        return Path(value) if value else Path(state_path("items", "instances.json"))

    @staticmethod
    def _fallback_path() -> Path:
        from . import items_instances as registry

        value = getattr(registry, "FALLBACK_INSTANCES_PATH", None)
        return Path(value) if value else Path(state_path("instances.json"))

    def _resolve_path(self) -> Path:
        primary = self._default_path()
        if primary.exists():
            return primary
        fallback = self._fallback_path()
        if fallback.exists():
            return fallback
        return primary

    def _load_raw(self, *, strict: Optional[bool] = None) -> List[Dict[str, Any]]:
        detect_duplicates, handle_duplicates, _, normalize_all, _, _ = self._helpers()

        target = self._resolve_path()
        try:
            with target.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except FileNotFoundError:
            return []
        except (PermissionError, IsADirectoryError, json.JSONDecodeError):
            self._LOG.error("Failed to load instances from %s", target, exc_info=True)
            raise

        if isinstance(payload, dict) and "instances" in payload:
            items = payload["instances"]
        elif isinstance(payload, list):
            items = payload
        else:
            items = []

        if not isinstance(items, list):
            return []

        duplicates = detect_duplicates(items)
        handle_duplicates(duplicates, strict=strict, path=target)

        normalize_all(items)
        return list(items)

    def snapshot(self) -> Iterable[Dict[str, Any]]:
        return self._load_raw()

    def replace_all(self, records: Iterable[Dict[str, Any]]) -> None:
        path = self._default_path()
        data = list(records)

        try:
            with path.open("r", encoding="utf-8") as fh:
                original = json.load(fh)
        except FileNotFoundError:
            original = []
        except (PermissionError, IsADirectoryError, json.JSONDecodeError):
            self._LOG.error("Failed to load existing instances from %s", path, exc_info=True)
            raise

        payload: Any
        if isinstance(original, dict) and "instances" in original:
            payload = {"instances": data}
        else:
            payload = data

        atomic_write_json(path, payload)

    def _find_index(self, iid: str, items: List[Dict[str, Any]]) -> Optional[int]:
        _, _, _, _, _, instance_id = self._helpers()
        target = str(iid)
        for idx, inst in enumerate(items):
            if instance_id(inst) == target:
                return idx
        return None

    @staticmethod
    def _owner_matches(inst: Dict[str, Any], owner: str) -> bool:
        if str(inst.get("owner", "")) == owner:
            return True
        meta = inst.get("meta")
        if isinstance(meta, dict):
            meta_owner = meta.get("owner")
            if isinstance(meta_owner, str) and meta_owner == owner:
                return True
        return False

    def get_by_iid(self, iid: str) -> Optional[Dict[str, Any]]:
        data = self._load_raw()
        target = str(iid)
        _, _, _, _, _, instance_id = self._helpers()
        for inst in data:
            if instance_id(inst) == target:
                return inst
        return None

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        data = self._load_raw()
        _, _, _, _, pos_of, _ = self._helpers()
        target = (int(year), int(x), int(y))
        matches: List[Dict[str, Any]] = []
        for inst in data:
            pos = pos_of(inst)
            if pos and pos == target:
                matches.append(inst)
        return matches

    def list_by_owner(self, owner: str) -> Iterable[Dict[str, Any]]:
        target = str(owner)
        data = self._load_raw()
        return [inst for inst in data if self._owner_matches(inst, target)]

    def mint(self, rec: Dict[str, Any]) -> None:
        items = self._load_raw()
        payload = dict(rec)
        _, _, normalize_one, _, _, _ = self._helpers()
        normalize_one(payload)
        items.append(payload)
        self.replace_all(items)

    def move(self, iid: str, *, year: int, x: int, y: int) -> None:
        items = self._load_raw()
        idx = self._find_index(iid, items)
        if idx is None:
            raise KeyError(iid)
        inst = items[idx]
        inst["pos"] = {"year": int(year), "x": int(x), "y": int(y)}
        inst["year"] = int(year)
        inst["x"] = int(x)
        inst["y"] = int(y)
        _, _, normalize_one, _, _, _ = self._helpers()
        normalize_one(inst)
        self.replace_all(items)

    def update_fields(self, iid: str, **fields: Any) -> None:
        items = self._load_raw()
        idx = self._find_index(iid, items)
        if idx is None:
            raise KeyError(iid)
        inst = items[idx]
        for key, value in fields.items():
            if value is None:
                inst.pop(key, None)
            else:
                inst[key] = value
        _, _, normalize_one, _, _, _ = self._helpers()
        normalize_one(inst)
        self.replace_all(items)

    def delete(self, iid: str) -> None:
        items = self._load_raw()
        idx = self._find_index(iid, items)
        if idx is None:
            return
        del items[idx]
        self.replace_all(items)


class JSONMonstersInstanceStore:
    """JSON-backed implementation of :class:`MonstersInstanceStore`."""

    __slots__ = ()

    @staticmethod
    def _resolve_path() -> Path:
        from . import monsters_instances as registry

        primary = Path(registry.DEFAULT_INSTANCES_PATH)
        fallback = Path(registry.FALLBACK_INSTANCES_PATH)
        if primary.exists():
            return primary
        if fallback.exists():
            return fallback
        return primary

    @classmethod
    def _load_raw(cls) -> List[Dict[str, Any]]:
        path = cls._resolve_path()
        if not path.exists():
            return []

        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (PermissionError, IsADirectoryError):
            raise
        except json.JSONDecodeError:
            return []

        if isinstance(data, dict) and "instances" in data:
            items = data["instances"]
        elif isinstance(data, list):
            items = data
        else:
            return []

        return [dict(inst) for inst in items if isinstance(inst, dict)]

    @staticmethod
    def _load():
        from . import monsters_instances

        return monsters_instances.load_monsters_instances()

    def snapshot(self) -> Iterable[Dict[str, Any]]:
        return list(self._load_raw())

    def replace_all(self, records: Iterable[Dict[str, Any]]) -> None:
        path = self._resolve_path()
        data = [dict(record) for record in records if isinstance(record, dict)]

        try:
            with path.open("r", encoding="utf-8") as fh:
                original = json.load(fh)
        except FileNotFoundError:
            original = []
        except (PermissionError, IsADirectoryError):
            raise
        except json.JSONDecodeError:
            original = []

        if isinstance(original, dict) and "instances" in original:
            payload: Any = {"instances": data}
        else:
            payload = data

        atomic_write_json(path, payload)

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
