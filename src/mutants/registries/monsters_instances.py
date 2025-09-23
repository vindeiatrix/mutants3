from __future__ import annotations
import json, random, uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from mutants.io.atomic import atomic_write_json
from mutants.registries.monsters_catalog import MonstersCatalog, exp_for

DEFAULT_INSTANCES_PATH = "state/monsters/instances.json"
FALLBACK_INSTANCES_PATH = "state/monsters.json"  # optional fallback; rarely used

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
    def __init__(self, path: str, items: List[Dict[str, Any]]):
        self._path = Path(path)
        self._items: List[Dict[str, Any]] = items
        self._by_id: Dict[str, Dict[str, Any]] = {m["instance_id"]: m for m in items if "instance_id" in m}
        self._dirty = False

    # ---------- Queries ----------
    def get(self, instance_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(instance_id)

    def list_all(self) -> Iterable[Dict[str, Any]]:
        return list(self._items)

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        return (m for m in self._items if m.get("pos") == [int(year), int(x), int(y)])

    # ---------- Mutations ----------
    def _add(self, inst: Dict[str, Any]) -> Dict[str, Any]:
        self._items.append(inst)
        self._by_id[inst["instance_id"]] = inst
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
        m = self._by_id[instance_id]; m["target_player_id"] = player_id; self._dirty = True

    def set_ready_target(self, instance_id: str, target_id: Optional[str]) -> None:
        monster = self._by_id[instance_id]
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
            atomic_write_json(self._path, self._items)
            self._dirty = False

def load_monsters_instances(path: str = DEFAULT_INSTANCES_PATH) -> MonstersInstances:
    primary = Path(path)
    fallback = Path(FALLBACK_INSTANCES_PATH)
    target = primary if primary.exists() else (fallback if fallback.exists() else primary)
    if not target.exists():
        return MonstersInstances(str(target), [])
    with target.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = []
    if isinstance(data, dict) and "instances" in data:
        items = data["instances"]
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return MonstersInstances(str(target), items)
