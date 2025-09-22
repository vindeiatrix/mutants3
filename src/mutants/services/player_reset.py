from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any, Dict, List
import json

from mutants.bootstrap.lazyinit import compute_ac_from_dex
from mutants.registries import items_instances as itemsreg
from mutants.services import player_state as pstate


def _load_templates() -> List[Dict[str, Any]]:
    """Load the starting class templates from packaged data."""

    try:
        with resources.open_text(
            "mutants.data", "startingclasstemplates.json", encoding="utf-8"
        ) as f:
            return json.load(f)
    except Exception:
        # Fallback for environments running from a checkout
        data_path = Path("src/mutants/data/startingclasstemplates.json")
        return json.loads(data_path.read_text(encoding="utf-8"))


def _template_for(cls_name: str, templates: List[Dict[str, Any]]) -> Dict[str, Any]:
    for t in templates:
        if (t.get("class") or "").lower() == (cls_name or "").lower():
            return t
    raise KeyError(f"No starting template for class: {cls_name}")


def _reset_fields_from_template(player: Dict[str, Any], template: Dict[str, Any]) -> None:
    stats = template.get("base_stats", {}) or {}
    dex = int(stats.get("dex", 0) or 0)
    hp_max = int(template.get("hp_max_start", 0) or 0)

    player["pos"] = list(template.get("start_pos", [2000, 0, 0]))
    player["stats"] = {
        "str": int(stats.get("str", 0) or 0),
        "int": int(stats.get("int", 0) or 0),
        "wis": int(stats.get("wis", 0) or 0),
        "dex": dex,
        "con": int(stats.get("con", 0) or 0),
        "cha": int(stats.get("cha", 0) or 0),
    }
    player["hp"] = {"current": hp_max, "max": hp_max}
    player["exhaustion"] = int(template.get("exhaustion_start", 0) or 0)
    player["exp_points"] = int(template.get("exp_start", 0) or 0)
    player["level"] = int(template.get("level_start", 1) or 1)
    player["riblets"] = int(template.get("riblets_start", 0) or 0)
    player["ions"] = int(template.get("ions_start", 0) or 0)
    player["armour"] = {
        "wearing": template.get("armour_start", None),
        "armour_class": compute_ac_from_dex(dex),
    }
    cls_name = str(player.get("class") or template.get("class") or "Thief")
    equipment_map = player.setdefault("equipment_by_class", {})
    equipment_map[cls_name] = {"armour": None}
    player.setdefault("wielded_by_class", {})[cls_name] = None
    player["wielded"] = None
    player["readied_spell"] = template.get("readied_spell_start", None)
    player["target_monster_id"] = None
    player["inventory"] = []
    player["carried_weight"] = 0
    player["conditions"] = {
        "poisoned": False,
        "encumbered": False,
        "ion_starving": False,
    }


def bury_by_index(index_0: int) -> Dict[str, Any]:
    """Reset the player at ``index_0`` (0-based) to their starting template."""

    state, _ = pstate.get_active_pair()
    players = state.get("players", [])
    if not (0 <= index_0 < len(players)):
        raise IndexError("Player index out of range")

    player = players[index_0]
    inventory_ids = [iid for iid in (player.get("inventory") or []) if iid]
    if inventory_ids:
        itemsreg.remove_instances(inventory_ids)

    templates = _load_templates()
    template = _template_for(player.get("class"), templates)
    _reset_fields_from_template(player, template)

    pstate.save_state(state)
    return state
