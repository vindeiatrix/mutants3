from __future__ import annotations
import json, random, uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# NOTE: Imported by ``mutants.registries.json_store`` via :func:`get_stores`.

from mutants.io.atomic import atomic_write_json
from mutants.registries.monsters_catalog import MonstersCatalog, exp_for
from mutants.state import state_path
from .storage import MonstersInstanceStore, get_stores

DEFAULT_INSTANCES_PATH = state_path("monsters", "instances.json")
FALLBACK_INSTANCES_PATH = state_path("monsters.json")  # optional fallback; rarely used

class MonstersInstances:
    """
    Mutable live monsters. Each entry is a dict:
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
        self._path = Path(path)
        self._store = store
        self._items: List[Dict[str, Any]] = [dict(entry) for entry in items if isinstance(entry, dict)]
        self._by_id: Dict[str, Dict[str, Any]] = {
            str(m["instance_id"]): m for m in self._items if "instance_id" in m
        }
        self._dirty = False

    # ---------- Queries ----------
    def get(self, instance_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(str(instance_id))

    def list_all(self) -> Iterable[Dict[str, Any]]:
        return list(self._items)

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        return (m for m in self._items if m.get("pos") == [int(year), int(x), int(y)])

    # ---------- Mutations ----------
    def _add(self, inst: Dict[str, Any]) -> Dict[str, Any]:
        self._items.append(inst)
        if "instance_id" in inst:
            self._by_id[str(inst["instance_id"])] = inst
        self._dirty = True
        return inst

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

        armour_wearing = starter_armour if starter_armour is not None else base.get("starter_armour", None)

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
                # Per-monster message template; tokens: {monster}, {target}, {damage}
                "message": base["innate_attack"].get(
                    "message",
                    "{monster} strikes {target} for {damage} damage!"
                )
            },
            "spells": list(base.get("spells", [])),
        }
        return self._add(inst)

    def set_target_player(self, instance_id: str, player_id: Optional[str]) -> None:
        target = self._by_id[str(instance_id)]
        target["target_player_id"] = player_id
        self._dirty = True

    def set_ready_target(self, instance_id: str, target_id: Optional[str]) -> None:
        monster = self._by_id[str(instance_id)]
        if target_id is None:
            sanitized = None
        else:
            sanitized = str(target_id).strip() or None
        monster["ready_target"] = sanitized
        monster["target_monster_id"] = sanitized
        self._dirty = True

    def set_target_monster(self, instance_id: str, other_id: Optional[str]) -> None:
        self.set_ready_target(instance_id, other_id)

    # ---------- Persistence ----------
    def save(self) -> None:
        if self._dirty:
            if self._store is not None:
                self._store.replace_all(self._items)
            else:
                atomic_write_json(self._path, self._items)
            self._dirty = False

def _resolve_instances_path(path: Path | str) -> Path:
    primary = Path(path)
    fallback = Path(FALLBACK_INSTANCES_PATH)
    if primary.exists():
        return primary
    if fallback.exists():
        return fallback
    return primary


def _load_instances_from_path(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError:
            return []

    if isinstance(data, dict) and "instances" in data:
        items = data["instances"]
    elif isinstance(data, list):
        items = data
    else:
        return []

    return [dict(entry) for entry in items if isinstance(entry, dict)]


def _load_instances_from_store(store: MonstersInstanceStore) -> List[Dict[str, Any]]:
    snapshot = store.snapshot()
    return [dict(entry) for entry in snapshot if isinstance(entry, dict)]


def load_monsters_instances(
    path: Path | str = DEFAULT_INSTANCES_PATH,
    *,
    store: MonstersInstanceStore | None = None,
) -> MonstersInstances:
    requested = Path(path)
    default_path = Path(DEFAULT_INSTANCES_PATH)
    fallback_path = Path(FALLBACK_INSTANCES_PATH)

    use_store = store is not None or requested in {default_path, fallback_path}

    if use_store:
        target = _resolve_instances_path(requested)
        active_store = store or get_stores().monsters
        items = _load_instances_from_store(active_store)
        return MonstersInstances(target, items, store=active_store)

    items = _load_instances_from_path(requested)
    return MonstersInstances(requested, items)
