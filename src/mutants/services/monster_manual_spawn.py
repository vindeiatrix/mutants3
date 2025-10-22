"""
Service for manually spawning a monster instance from a template.
"""
from __future__ import annotations

import random
import json
from typing import Any, Mapping, Sequence

from mutants.registries import (
    items_catalog,
    items_instances,
    monsters_catalog,
    monsters_instances,
)
from mutants.services import monster_entities
from mutants.util import ids as id_utils

# Helper to get a random number for the unique suffix
_RNG = random.Random()


def _get_next_suffix_id(
    monsters_reg: monsters_instances.MonstersInstances,
    base_name: str,
) -> int:
    """Finds the next available numeric suffix for a monster."""

    def _extract_name(inst: Mapping[str, Any]) -> str | None:
        """Best-effort extraction of the monster display name.

        Instances returned by :class:`MonstersInstances` are usually fully
        normalized and expose the ``name`` field directly. However, legacy
        rows – especially those minted by external tooling – may still have
        the name embedded inside the serialized ``stats_json`` payload. The
        manual spawn command should treat both formats identically so that the
        suffix generator can see all existing names and avoid duplicates.
        """

        name = inst.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()

        # Fall back to decoding ``stats_json`` if present. This mirrors the
        # logic in ``SQLiteMonstersInstanceStore._row_to_payload`` where the
        # field is normally unpacked.
        stats_json = inst.get("stats_json")
        if isinstance(stats_json, str) and stats_json.strip():
            try:
                decoded = json.loads(stats_json)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, Mapping):
                raw_name = decoded.get("name")
                if isinstance(raw_name, str) and raw_name.strip():
                    return raw_name.strip()
        return None

    current_suffixes = set()
    prefix = f"{base_name}-"
    for inst in monsters_reg.list_all():
        if not isinstance(inst, Mapping):
            continue
        name = _extract_name(inst)
        if isinstance(name, str) and name.startswith(prefix):
            try:
                suffix = int(name[len(prefix) :])
                current_suffixes.add(suffix)
            except (TypeError, ValueError):
                continue

    if not current_suffixes:
        return _RNG.randint(100, 999)  # Start with 3 digits if none

    # Find the max and add a random amount to it, max 9999
    next_id = max(current_suffixes) + _RNG.randint(1, 5)
    if next_id > 9999:
        # Fallback: find first free slot
        for i in range(1, 10000):
            if i not in current_suffixes:
                return i
        return 9999  # Should be unreachable
    return next_id


def _create_monster_items(
    template: monster_entities.MonsterTemplate,
    monster_instance_id: str,
    pos: Sequence[int] | Mapping[str, Any] | None,
    items_cat: items_catalog.ItemsCatalog,
    items_reg: items_instances.ItemsInstances,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Creates item instances for the monster's starting gear and returns
    the monster inventory list and the instance_id of the equipped armour.
    """
    inventory_list: list[dict[str, Any]] = []
    armour_iid: str | None = None
    
    # Mint starter items
    for item_id in template.starter_items:
        item_template = items_cat.get_item(item_id)
        if not item_template:
            continue  # Item doesn't exist in catalog

        instance = items_reg.mint_item(
            item_id=item_id,
            pos=pos,
            owner_iid=monster_instance_id,
            origin="monster_native",
        )
        if instance:
            inventory_list.append({"instance_id": instance["instance_id"]})

    # Mint and equip starter armour
    if template.starter_armour:
        armour_id = template.starter_armour[0]
        armour_template = items_cat.get_item(armour_id)
        if armour_template:
            instance = items_reg.mint_item(
                item_id=armour_id,
                pos=pos,
                owner_iid=monster_instance_id,
                origin="monster_native",
            )
            if instance:
                armour_iid = instance["instance_id"]
                # Add to inventory
                inventory_list.append({"instance_id": armour_iid})

    return inventory_list, armour_iid


def spawn_monster_at(
    monster_id: str,
    pos: Sequence[int] | Mapping[str, Any] | None,
    monsters_cat: monsters_catalog.MonstersCatalog,
    monsters_reg: monsters_instances.MonstersInstances,
    items_cat: items_catalog.ItemsCatalog,
    items_reg: items_instances.ItemsInstances,
) -> dict[str, Any] | None:
    """
    Mints a new monster instance from a template and adds it to the registry.
    This function creates the unique name.
    """
    import logging

    LOG = logging.getLogger(__name__)
    LOG.warning(
        ">>> spawn_monster_at called for %s at %s", monster_id, pos
    )

    template = monsters_cat.get_template(monster_id)
    if not template:
        return None

    instance_id = id_utils.new_instance_id()
    base_name = template.name or "Monster"
    suffix = _get_next_suffix_id(monsters_reg, base_name)
    unique_name = f"{base_name}-{suffix}"

    coords: list[int]
    if isinstance(pos, Mapping):
        coords = [
            int(pos.get("year", 0) or 0),
            int(pos.get("x", 0) or 0),
            int(pos.get("y", 0) or 0),
        ]
    elif isinstance(pos, Sequence) and len(pos) >= 3:
        try:
            coords = [int(pos[0]), int(pos[1]), int(pos[2])]
        except (TypeError, ValueError):
            coords = [0, 0, 0]
    else:
        coords = [0, 0, 0]

    inventory, armour_iid = _create_monster_items(
        template, instance_id, coords, items_cat, items_reg
    )

    hp = max(1, template.hp_max or 1)
    ions_min = template.ions_min if template.ions_min is not None else 0
    ions_max = template.ions_max if template.ions_max is not None else ions_min
    if ions_max < ions_min:
        ions_max = ions_min

    rib_min = template.riblets_min if template.riblets_min is not None else 0
    rib_max = template.riblets_max if template.riblets_max is not None else rib_min
    if rib_max < rib_min:
        rib_max = rib_min

    instance_data = {
        "instance_id": instance_id,
        "monster_id": template.monster_id,
        "name": unique_name,  # This is the new unique name!
        "pos": coords,
        "hp": {"current": hp, "max": hp},
        "armour_class": template.armour_class or 0,
        "level": template.level or 1,
        "ions": _RNG.randint(ions_min, ions_max),
        "riblets": _RNG.randint(rib_min, rib_max),
        "inventory": inventory,
        "armour_wearing": armour_iid,
        "readied_spell": None,
        "target_player_id": None,
        "target_monster_id": None,
        "ready_target": None,
        "taunt": template.taunt or "",
        "innate_attack": monster_entities.copy_innate_attack(
            template.innate_attack, base_name
        ),
        "spells": list(template.spells or []),
        "stats": dict(template.stats or {}),
        "derived": {},  # Add derived key for schema validation
    }

    # Add to registry and save
    if monsters_reg.add_instance(instance_data):
        monsters_reg.save()
        LOG.warning(
            "<<< spawn_monster_at SUCCESS for %s, name=%s",
            instance_id,
            instance_data.get("name"),
        )
        return instance_data

    return None
