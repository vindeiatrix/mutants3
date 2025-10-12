from __future__ import annotations

import json
import logging
import sqlite3
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List

from mutants import env
from mutants.bootstrap.lazyinit import compute_ac_from_dex
from mutants.players import startup as player_startup
from mutants.services import player_state as pstate


LOG = logging.getLogger(__name__)


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


def _reset_fields_from_template(
    player: Dict[str, Any],
    template: Dict[str, Any],
    *,
    reason: str | None = None,
    state: Dict[str, Any] | None = None,
) -> None:
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
    player["armour"] = {
        "wearing": template.get("armour_start", None),
        "armour_class": compute_ac_from_dex(dex),
    }
    cls_name = str(player.get("class") or template.get("class") or "Thief")
    equipment_map = player.setdefault("equipment_by_class", {})
    equipment_map[cls_name] = {"armour": None}
    player.setdefault("wielded_by_class", {})[cls_name] = None
    player.setdefault("ready_target_by_class", {})[cls_name] = None
    player["wielded"] = None
    player["readied_spell"] = template.get("readied_spell_start", None)
    player["ready_target"] = None
    player["target_monster_id"] = None
    player["inventory"] = []
    player["carried_weight"] = 0
    bags = player.get("bags")
    if not isinstance(bags, dict):
        bags = {}
        player["bags"] = bags
    bags[cls_name] = []
    player["conditions"] = {
        "poisoned": False,
        "encumbered": False,
        "ion_starving": False,
    }

    if reason:
        player_startup.grant_starting_ions(player, reason, state=state)
    else:
        player["ions"] = int(template.get("ions_start", 0) or 0)
        player["Ions"] = player["ions"]


def _purge_player_items(player_id: str) -> int:
    if not player_id:
        LOG.info("Removed 0 item rows for <unknown> during bury")
        return 0

    db_path = env.get_state_database_path()
    removed = 0
    try:
        with sqlite3.connect(db_path) as con:
            con.execute("PRAGMA foreign_keys=ON")
            cur = con.execute(
                "DELETE FROM items_instances WHERE owner = ?",
                (player_id,),
            )
            removed = cur.rowcount or 0
            try:
                con.execute(
                    "UPDATE players SET wield_item_id=NULL, armour_item_id=NULL "
                    "WHERE player_id=?",
                    (player_id,),
                )
            except sqlite3.OperationalError:
                LOG.debug(
                    "players table missing while clearing equipment for %s",
                    player_id,
                    exc_info=True,
                )
    except sqlite3.OperationalError as exc:
        LOG.debug(
            "Skipping inventory purge for %s due to missing tables: %s",
            player_id,
            exc,
            exc_info=True,
        )
    except sqlite3.Error as exc:
        LOG.warning("Failed to purge inventory for %s: %s", player_id, exc)
    finally:
        LOG.info("Removed %d item rows for %s during bury", removed, player_id)
    return removed


def bury_by_index(index_0: int) -> Dict[str, Any]:
    """Reset the player at ``index_0`` (0-based) to their starting template."""

    state, active = pstate.get_active_pair()
    players = state.get("players", [])
    if not (0 <= index_0 < len(players)):
        raise IndexError("Player index out of range")

    player = players[index_0]
    player_id = str(player.get("id") or "")
    _purge_player_items(player_id)

    templates = _load_templates()
    template = _template_for(player.get("class"), templates)
    _reset_fields_from_template(
        player,
        template,
        reason="buried",
        state=state,
    )
    active_id = state.get("active_id")
    if (
        isinstance(active, dict)
        and active is not player
        and player_id
        and active_id == player_id
    ):
        _reset_fields_from_template(
            active,
            template,
            reason="buried",
            state=state,
        )
    root_class = state.get("class") or state.get("name")
    player_class = player.get("class") or template.get("class")
    if (
        isinstance(root_class, str)
        and isinstance(player_class, str)
        and root_class.strip().lower() == player_class.strip().lower()
    ):
        _reset_fields_from_template(
            state,
            template,
            reason="buried",
            state=state,
        )

    pstate.save_state(state)
    return state
