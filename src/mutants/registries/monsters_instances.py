from __future__ import annotations

import json
import random
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# NOTE: Imported by ``mutants.registries.json_store`` via :func:`get_stores`.

from mutants.registries import items_instances as itemsreg
from mutants.registries.monsters_catalog import MonstersCatalog, exp_for
from mutants.services.monster_entities import DEFAULT_INNATE_ATTACK_LINE
from mutants.state import state_path
from .storage import MonstersInstanceStore, get_stores

DEFAULT_INSTANCES_PATH = state_path("monsters", "instances.json")
FALLBACK_INSTANCES_PATH = state_path("monsters.json")  # optional fallback; rarely used

_STAT_KEYS = ("str", "dex", "con", "int", "wis", "cha")


def _copy_stats(base: Mapping[str, Any]) -> Dict[str, int]:
    stats_raw = base.get("stats") if isinstance(base, Mapping) else None
    stats: Dict[str, int] = {}
    if isinstance(stats_raw, Mapping):
        for key in _STAT_KEYS:
            try:
                stats[key] = int(stats_raw.get(key, 0))
            except (TypeError, ValueError):
                stats[key] = 0
    else:
        stats = {key: 0 for key in _STAT_KEYS}
    return stats


def _sanitize_base_name(base: Mapping[str, Any]) -> str:
    raw_name = base.get("name") or base.get("monster_id") or "Monster"
    name = str(raw_name).strip()
    return name or "Monster"


def _format_display_name(name: str, suffix: int) -> str:
    token = name if isinstance(name, str) and name.strip() else "Monster"
    return f"{token}-{suffix}"

class MonstersInstances:
    """
    Mutable live monsters backed by the configured state store.

    Each entry is a dict with the following shape::

        {
          instance_id, monster_id, pos:[year,x,y],
          hp:{current,max}, armour_class, level, ions, riblets,
          inventory:[{item_id|instance_id, qty?}] (<=4),
          armour_wearing: item_id|instance_id|null,
          readied_spell: spell_id|null,
          target_player_id: str|null, target_monster_id: str|null,
          ready_target: str|null,
          taunt: str
        }
    """

    def __init__(
        self,
        path: Path | str,
        items: List[Dict[str, Any]],
        *,
        store: MonstersInstanceStore | None = None,
    ):
        # ``path`` and ``items`` are retained for backwards compatibility with
        # historical call sites. Persistence is now exclusively handled by the
        # injected store so we no longer maintain an in-memory snapshot.
        self._path = Path(path)
        self._store = store or get_stores().monsters
        self._suffix_cache: Dict[str, int] = {}

    # ---------- Internal helpers ----------
    @staticmethod
    def _coerce_int(value: Any, *, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _ensure_store(self) -> MonstersInstanceStore:
        if self._store is None:  # pragma: no cover - defensive
            raise RuntimeError("MonstersInstances requires an active store")
        return self._store

    def _persist_payload(self, payload: Dict[str, Any]) -> None:
        store = self._ensure_store()
        instance_id = payload.get("instance_id")
        if instance_id is None:
            raise KeyError("instance_id")

        pos = payload.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            year, x, y = (self._coerce_int(part) for part in pos)
        else:
            year = self._coerce_int(payload.get("year"))
            x = self._coerce_int(payload.get("x"))
            y = self._coerce_int(payload.get("y"))
            payload["pos"] = [year, x, y]

        hp = payload.get("hp")
        if isinstance(hp, dict):
            hp_cur = self._coerce_int(hp.get("current"))
            hp_max = self._coerce_int(hp.get("max"), default=hp_cur)
        else:
            hp_cur = self._coerce_int(payload.get("hp_cur"))
            hp_max = self._coerce_int(payload.get("hp_max"), default=hp_cur)
            payload["hp"] = {"current": hp_cur, "max": hp_max}

        timers_payload = payload.get("status_effects") or payload.get("timers") or []
        if timers_payload:
            timers_json = json.dumps(
                {"status_effects": timers_payload},
                sort_keys=True,
                separators=(",", ":"),
            )
        else:
            timers_json = None

        store.update_fields(
            str(instance_id),
            stats_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            year=year,
            x=x,
            y=y,
            hp_cur=hp_cur,
            hp_max=hp_max,
            timers_json=timers_json,
        )

    def _mutate_payload(self, instance_id: str, mutator) -> None:
        record = self.get(instance_id)
        if record is None:
            raise KeyError(str(instance_id))
        mutator(record)
        self._persist_payload(record)

    def _add(self, inst: Dict[str, Any]) -> Dict[str, Any]:
        store = self._ensure_store()
        payload = dict(inst)
        instance_id = payload.get("instance_id")
        if instance_id is None:
            raise KeyError("instance_id")
        store.spawn(payload)
        stored = store.get(str(instance_id))
        record = stored if isinstance(stored, dict) else payload
        self._update_suffix_cache(record)
        return record

    def _merge_stats_payload(self, record: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(record)
        stats_json = merged.get("stats_json")
        if isinstance(stats_json, str) and stats_json.strip():
            try:
                decoded = json.loads(stats_json)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, Mapping):
                for key, value in decoded.items():
                    merged.setdefault(key, value)
        return merged

    def _extract_suffix(self, record: Mapping[str, Any]) -> Optional[int]:
        suffix = record.get("instance_suffix")
        if isinstance(suffix, int) and suffix >= 0:
            return suffix
        if isinstance(suffix, str) and suffix.isdigit():
            return int(suffix)
        stats_block = record.get("stats")
        stats_display = None
        if isinstance(stats_block, Mapping):
            stats_display = stats_block.get("display_name")
        name_source = record.get("display_name") or record.get("name") or stats_display
        if isinstance(name_source, str):
            token = name_source.strip()
            match = re.search(r"-(\d+)$", token)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    return None
        return None

    def _update_suffix_cache(self, record: Mapping[str, Any]) -> None:
        monster_id = record.get("monster_id")
        if not monster_id:
            return
        monster_token = str(monster_id)
        suffix = self._extract_suffix(record)
        if suffix is None:
            return
        current = self._suffix_cache.get(monster_token, 0)
        if suffix > current:
            self._suffix_cache[monster_token] = suffix

    def next_instance_suffix(self, monster_id: str) -> int:
        token = str(monster_id)
        if token not in self._suffix_cache:
            max_suffix = 0
            try:
                for record in self.list_all():
                    if not isinstance(record, Mapping):
                        continue
                    if str(record.get("monster_id")) != token:
                        continue
                    suffix = self._extract_suffix(record)
                    if suffix is not None and suffix > max_suffix:
                        max_suffix = suffix
            except Exception:
                max_suffix = 0
            self._suffix_cache[token] = max_suffix
        self._suffix_cache[token] += 1
        return self._suffix_cache[token]

    def spawn(self, inst: Dict[str, Any]) -> Dict[str, Any]:
        return self._add(inst)

    def move(self, instance_id: str, *, year: int, x: int, y: int) -> None:
        target_pos = [self._coerce_int(year), self._coerce_int(x), self._coerce_int(y)]

        def _mutator(record: Dict[str, Any]) -> None:
            record["pos"] = target_pos

        self._mutate_payload(instance_id, _mutator)

    def create_instance(
        self,
        base: Dict[str, Any],
        pos: Tuple[int,int,int],
        *,
        rng: Optional[random.Random] = None,
        level: Optional[int] = None,
        ions: Optional[int] = None,
        riblets: Optional[int] = None,
        starter_items: Optional[List[Dict[str, Any]]] = None,  # [{item_id|instance_id, qty?}]
        starter_armour: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a live monster from a catalog base. Randomizes ions/riblets within
        min/max if not provided. Seeds HP/max, AC, level. Copies taunt.
        """
        rr = rng or random.Random()
        year, x, y = map(int, pos)
        instance_id = f"{base['monster_id']}#{uuid.uuid4().hex[:8]}"
        base_name = _sanitize_base_name(base)
        suffix = self.next_instance_suffix(str(base["monster_id"]))
        display_name = _format_display_name(base_name, suffix)

        lvl = int(level if level is not None else base.get("level", 1))
        ions_rng = (int(base.get("ions_min", 0)), int(base.get("ions_max", 0)))
        rib_rng = (int(base.get("riblets_min", 0)), int(base.get("riblets_max", 0)))
        ions_val = int(ions if ions is not None else rr.randint(*ions_rng))
        rib_val = int(riblets if riblets is not None else rr.randint(*rib_rng))

        raw_entries: List[Any] = list(starter_items or [])
        if not raw_entries:
            # Simple seeding from catalog (<=4)
            for iid in base.get("starter_items", [])[:4]:
                raw_entries.append({"item_id": iid})

        armour_source = starter_armour if starter_armour is not None else base.get("starter_armour")
        armour_token: Optional[str]
        if isinstance(armour_source, (list, tuple)):
            armour_choices = [str(a) for a in armour_source if isinstance(a, (str, int))]
            armour_token = armour_choices[0] if armour_choices else None
        elif armour_source is None or isinstance(armour_source, (str, int)):
            armour_token = str(armour_source) if armour_source not in (None, "") else None
        else:
            armour_token = None

        bag_entries: List[Dict[str, Any]] = []
        for raw_entry in raw_entries:
            if len(bag_entries) >= 4:
                break
            entry: Dict[str, Any]
            if isinstance(raw_entry, Mapping):
                item_id = (
                    raw_entry.get("item_id")
                    or raw_entry.get("catalog_id")
                    or raw_entry.get("id")
                )
                if not item_id:
                    continue
                entry = {"item_id": str(item_id)}
                qty = raw_entry.get("qty")
                if isinstance(qty, int) and qty > 1:
                    entry["qty"] = qty
                origin = raw_entry.get("origin")
                if isinstance(origin, str) and origin.strip():
                    entry["origin"] = origin.strip().lower()
            else:
                entry = {"item_id": str(raw_entry)}
            iid = itemsreg.mint_iid()
            entry["iid"] = iid
            entry["instance_id"] = iid
            entry.setdefault("origin", "native")
            bag_entries.append(entry)

        armour_wearing = None
        if armour_token:
            for entry in bag_entries:
                if entry.get("item_id") == armour_token:
                    armour_wearing = entry.get("iid")
                    break

        inst: Dict[str, Any] = {
            "instance_id": instance_id,
            "monster_id": base["monster_id"],
            "pos": [year, x, y],
            "hp": {"current": int(base["hp_max"]), "max": int(base["hp_max"])},
            "armour_class": int(base["armour_class"]),
            "level": lvl,
            "ions": ions_val,
            "riblets": rib_val,
            "stats": _copy_stats(base),
            "inventory": [dict(entry) for entry in bag_entries],
            "bag": [dict(entry) for entry in bag_entries],
            "armour_wearing": armour_wearing,
            "wielded": bag_entries[0]["iid"] if bag_entries else None,
            "readied_spell": None,
            "target_player_id": None,
            "target_monster_id": None,
            "ready_target": None,
            "taunt": base.get("taunt", ""),
            # Copy innate attack block for quick access (optional, but handy for combat)
            "innate_attack": {
                "name": base["innate_attack"]["name"],
                "power_base": int(base["innate_attack"]["power_base"]),
                "power_per_level": int(base["innate_attack"]["power_per_level"]),
                # Per-monster attack line template; tokens: {monster}, {attack}, {target}
                "line": base["innate_attack"].get("line", DEFAULT_INNATE_ATTACK_LINE),
            },
            "spells": list(base.get("spells", [])),
        }
        inst["base_name"] = base_name
        inst["instance_suffix"] = suffix
        inst["display_name"] = display_name
        inst["name"] = display_name
        return self._add(inst)

    def set_target_player(self, instance_id: str, player_id: Optional[str]) -> None:
        def _mutator(record: Dict[str, Any]) -> None:
            record["target_player_id"] = player_id

        self._mutate_payload(instance_id, _mutator)

    def set_ready_target(self, instance_id: str, target_id: Optional[str]) -> None:
        if target_id is None:
            sanitized: Optional[str] = None
        else:
            sanitized = str(target_id).strip() or None

        def _mutator(record: Dict[str, Any]) -> None:
            record["ready_target"] = sanitized
            record["target_monster_id"] = sanitized

        self._mutate_payload(instance_id, _mutator)

    def set_target_monster(self, instance_id: str, other_id: Optional[str]) -> None:
        self.set_ready_target(instance_id, other_id)

    # ---------- Persistence ----------
    def save(self) -> None:
        # Persistence is immediate via the backing store; the method is kept
        # for compatibility with existing call sites.
        return None

    # ---------- Queries ----------
    def get(self, instance_id: str) -> Optional[Dict[str, Any]]:
        store = self._ensure_store()
        record = store.get(str(instance_id))
        if isinstance(record, dict):
            merged = self._merge_stats_payload(record)
            self._update_suffix_cache(merged)
            return merged
        return record

    def list_all(self) -> Iterable[Dict[str, Any]]:
        store = self._ensure_store()
        payloads = []
        for record in store.snapshot():
            if isinstance(record, dict):
                merged = self._merge_stats_payload(record)
                self._update_suffix_cache(merged)
                payloads.append(merged)
        return payloads

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        store = self._ensure_store()
        results: List[Dict[str, Any]] = []
        for raw in store.list_at(
            self._coerce_int(year),
            self._coerce_int(x),
            self._coerce_int(y),
        ):
            if not isinstance(raw, dict):
                continue
            merged = self._merge_stats_payload(raw)
            self._update_suffix_cache(merged)
            results.append(merged)
        return results

    # ---------- Direct store helpers ----------
    def update_fields(self, instance_id: str, **fields: Any) -> None:
        self._ensure_store().update_fields(str(instance_id), **fields)

    def delete(self, instance_id: str) -> None:
        self._ensure_store().delete(str(instance_id))

def load_monsters_instances(
    path: Path | str = DEFAULT_INSTANCES_PATH,
    *,
    store: MonstersInstanceStore | None = None,
) -> MonstersInstances:
    # ``path`` is retained for backwards compatibility with legacy callers.
    # Persistence now flows through the configured store regardless of the
    # provided path so no JSON files are read or written.
    active_store = store or get_stores().monsters
    return MonstersInstances(Path(path), [], store=active_store)
