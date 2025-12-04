from __future__ import annotations

import json
import logging
import sqlite3
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, MutableMapping

from mutants import env
from mutants.bootstrap.lazyinit import compute_ac_from_dex
from mutants.players import startup as player_startup
from mutants.services import player_state as pstate
from mutants.constants import CLASS_ORDER


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


def _set_class_map_entry(
    target: MutableMapping[str, Any] | None, map_name: str, cls_name: str, value: Any
) -> None:
    if not isinstance(target, MutableMapping):
        return
    mapping = target.get(map_name)
    if not isinstance(mapping, MutableMapping):
        mapping = {}
        target[map_name] = mapping
    mapping[cls_name] = value


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
    level_start = int(template.get("level_start", 1) or 1)
    exp_start = int(template.get("exp_start", 0) or 0)
    riblets_start = int(template.get("riblets_start", 0) or 0)
    exhaustion_start = int(template.get("exhaustion_start", 0) or 0)

    player["pos"] = list(template.get("start_pos", [2000, 0, 0]))
    stats_block = {
        "str": int(stats.get("str", 0) or 0),
        "int": int(stats.get("int", 0) or 0),
        "wis": int(stats.get("wis", 0) or 0),
        "dex": dex,
        "con": int(stats.get("con", 0) or 0),
        "cha": int(stats.get("cha", 0) or 0),
    }
    player["stats"] = stats_block
    hp_block = {"current": hp_max, "max": hp_max}
    player["hp"] = hp_block
    player["exhaustion"] = exhaustion_start
    player["exp_points"] = exp_start
    player["level"] = level_start
    player["riblets"] = riblets_start
    player["armour"] = {
        "wearing": template.get("armour_start", None),
        "armour_class": compute_ac_from_dex(dex),
    }
    cls_name = str(player.get("class") or template.get("class") or "Thief")
    equipment_map = player.setdefault("equipment_by_class", {})
    equipment_map[cls_name] = {"armour": None}
    player.setdefault("wielded_by_class", {})[cls_name] = None
    player.setdefault("ready_target_by_class", {})[cls_name] = None
    player.setdefault("target_monster_id_by_class", {})[cls_name] = None
    player["wielded"] = None
    player["readied_spell"] = template.get("readied_spell_start", None)
    player["ready_target"] = None
    player["target_monster_id"] = None
    player["status_effects"] = []
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

    ions_amount = int(template.get("ions_start", 0) or 0)
    if reason:
        ions_amount = player_startup.grant_starting_ions(player, reason, state=state)
    else:
        player["ions"] = ions_amount
        player["Ions"] = ions_amount

    map_targets: List[MutableMapping[str, Any]] = []
    if isinstance(player, MutableMapping):
        map_targets.append(player)
    if isinstance(state, MutableMapping) and state is not player:
        map_targets.append(state)
    for target in map_targets:
        _set_class_map_entry(target, "ions_by_class", cls_name, ions_amount)
        _set_class_map_entry(target, "riblets_by_class", cls_name, riblets_start)
        _set_class_map_entry(target, "exhaustion_by_class", cls_name, exhaustion_start)
        _set_class_map_entry(target, "exp_by_class", cls_name, exp_start)
        _set_class_map_entry(target, "level_by_class", cls_name, level_start)
        _set_class_map_entry(target, "hp_by_class", cls_name, dict(hp_block))
        _set_class_map_entry(target, "stats_by_class", cls_name, dict(stats_block))
        _set_class_map_entry(target, "ready_target_by_class", cls_name, None)
        _set_class_map_entry(target, "target_monster_id_by_class", cls_name, None)
        _set_class_map_entry(target, "status_effects_by_class", cls_name, [])
        _set_class_map_entry(target, "equipment_by_class", cls_name, {"armour": None})

        target_bags = target.get("bags")
        if not isinstance(target_bags, MutableMapping):
            target_bags = {}
            target["bags"] = target_bags
        target_bags[cls_name] = []


def _reset_player_profile(
    player: Dict[str, Any],
    template: Dict[str, Any],
    *,
    state: Dict[str, Any],
    active: Dict[str, Any],
) -> None:
    """Reset a single player entry and mirror state/active snapshots."""

    player_id = str(player.get("id") or "")
    _purge_player_items(player_id)

    _reset_fields_from_template(
        player,
        template,
        reason="buried",
        state=state,
    )

    if (
        isinstance(active, dict)
        and active is not player
        and player_id
        and state.get("active_id") == player_id
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


def bury_class(class_name: str) -> Dict[str, Any]:
    """Reset the player matching ``class_name`` to their starting template."""

    state, active = pstate.get_active_pair()
    if isinstance(state, dict):
        pstate.ensure_class_profiles(state)
        state, active = pstate.get_active_pair(state)

    normalized_cls = pstate.normalize_class_name(class_name) or "Thief"
    players = state.get("players", [])
    player: Dict[str, Any] | None = None
    if isinstance(players, list):
        for entry in players:
            if not isinstance(entry, dict):
                continue
            entry_class = pstate.normalize_class_name(entry.get("class")) or pstate.normalize_class_name(
                entry.get("name")
            )
            if entry_class == normalized_cls:
                player = entry
                break
    if player is None:
        raise KeyError(f"No player profile for class: {normalized_cls}")

    templates = _load_templates()
    template = _template_for(normalized_cls, templates)
    _reset_player_profile(player, template, state=state, active=active)

    pstate.ensure_class_profiles(state)
    pstate.save_state(state)
    return state


def bury_by_index(index_0: int) -> Dict[str, Any]:
    """Reset the player at ``index_0`` (0-based) to their starting template."""

    if not (0 <= index_0 < len(CLASS_ORDER)):
        raise IndexError("Player index out of range")

    class_name = CLASS_ORDER[index_0]
    return bury_class(class_name)


def bury_all() -> Dict[str, Any]:
    """Reset all player classes to their starting templates."""

    state, active = pstate.get_active_pair()
    if isinstance(state, dict):
        pstate.ensure_class_profiles(state)
        state, active = pstate.get_active_pair(state)

    players = state.get("players", [])
    templates = _load_templates()

    if not isinstance(players, list):
        return state

    for class_name in CLASS_ORDER:
        normalized_cls = pstate.normalize_class_name(class_name) or "Thief"
        player = None
        for entry in players:
            if not isinstance(entry, dict):
                continue
            entry_class = pstate.normalize_class_name(entry.get("class")) or pstate.normalize_class_name(
                entry.get("name")
            )
            if entry_class == normalized_cls:
                player = entry
                break
        if player is None:
            continue
        template = _template_for(normalized_cls, templates)
        _reset_player_profile(player, template, state=state, active=active)

    pstate.ensure_class_profiles(state)
    pstate.save_state(state)
    return state
