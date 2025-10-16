from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# NOTE: Imported by ``mutants.registries.json_store`` via :func:`get_stores`.

from mutants.registries.monsters_catalog import MonstersCatalog, exp_for
from mutants.services.monster_entities import DEFAULT_INNATE_ATTACK_LINE
from mutants.state import state_path
from .storage import MonstersInstanceStore, get_stores

DEFAULT_INSTANCES_PATH = state_path("monsters", "instances.json")
FALLBACK_INSTANCES_PATH = state_path("monsters.json")  # optional fallback; rarely used

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
        return stored or payload

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

        lvl = int(level if level is not None else base.get("level", 1))
        ions_rng = (int(base.get("ions_min", 0)), int(base.get("ions_max", 0)))
        rib_rng = (int(base.get("riblets_min", 0)), int(base.get("riblets_max", 0)))
        ions_val = int(ions if ions is not None else rr.randint(*ions_rng))
        rib_val = int(riblets if riblets is not None else rr.randint(*rib_rng))

        inv = list(starter_items or [])
        if not inv:
            # Simple seeding from catalog (<=4)
            for iid in base.get("starter_items", [])[:4]:
                inv.append({"item_id": iid})

        armour_source = starter_armour if starter_armour is not None else base.get("starter_armour")
        if isinstance(armour_source, (list, tuple)):
            armour_choices = [str(a) for a in armour_source if isinstance(a, (str, int))]
            armour_wearing = armour_choices[0] if armour_choices else None
        elif armour_source is None or isinstance(armour_source, (str, int)):
            armour_wearing = str(armour_source) if armour_source not in (None, "") else None
        else:
            armour_wearing = None

        inst: Dict[str, Any] = {
            "instance_id": instance_id,
            "monster_id": base["monster_id"],
            "pos": [year, x, y],
            "hp": {"current": int(base["hp_max"]), "max": int(base["hp_max"])},
            "armour_class": int(base["armour_class"]),
            "level": lvl,
            "ions": ions_val,
            "riblets": rib_val,
            "inventory": inv[:4],
            "armour_wearing": armour_wearing,
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
        return dict(record) if isinstance(record, dict) else record

    def list_all(self) -> Iterable[Dict[str, Any]]:
        store = self._ensure_store()
        return list(store.snapshot())

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        store = self._ensure_store()
        return list(
            store.list_at(
                self._coerce_int(year),
                self._coerce_int(x),
                self._coerce_int(y),
            )
        )

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
