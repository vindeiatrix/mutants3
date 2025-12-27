"""Monster inventory helpers focused on cracked gear handling."""

from __future__ import annotations

import random
from typing import Any, Mapping, MutableMapping, Optional

from mutants.debug import turnlog
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import combat_loot, monsters_state
from mutants.ui import item_display, textutils

DROP_KIND_WEAPON = "weapon"
WEAPON_DROP_CHANCE = 80


def _ai_state(monster: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    state = monster.get("_ai_state")
    if not isinstance(state, MutableMapping):
        state = {}
        monster["_ai_state"] = state
    return state


def _monster_id(monster: Mapping[str, Any]) -> str:
    for key in ("id", "instance_id", "monster_id"):
        raw = monster.get(key)
        if raw is None:
            continue
        token = str(raw).strip()
        if token:
            return token
    return "?"


def _monster_display_name(monster: Mapping[str, Any]) -> str:
    name = monster.get("name") or monster.get("monster_id")
    if isinstance(name, str) and name:
        return name
    ident = monster.get("id") or monster.get("instance_id")
    if isinstance(ident, str) and ident:
        return ident
    return "The monster"


def _mark_monsters_dirty(ctx: Mapping[str, Any], monster: Mapping[str, Any] | str | None = None) -> None:
    monsters = ctx.get("monsters") if isinstance(ctx, Mapping) else None
    marker = getattr(monsters, "mark_dirty", None)
    if callable(marker):
        try:
            marker(monster)
        except Exception:  # pragma: no cover - defensive
            pass


def _refresh_monster(monster: MutableMapping[str, Any]) -> bool:
    try:
        return bool(monsters_state._refresh_monster_derived(monster))
    except Exception:  # pragma: no cover - defensive
        return False


def _load_catalog() -> Mapping[str, Mapping[str, Any]]:
    try:
        catalog = items_catalog.load_catalog()
    except FileNotFoundError:
        catalog = None
    if isinstance(catalog, Mapping):
        return catalog
    return {}


def _resolve_pos(monster: Mapping[str, Any]) -> Optional[tuple[int, int, int]]:
    pos = combat_loot.coerce_pos(monster.get("pos"))
    if pos is not None:
        return pos
    return None


def _normalize_pending(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    kind = str(payload.get("kind") or "").strip().lower()
    if kind != DROP_KIND_WEAPON:
        return None
    iid = payload.get("iid")
    if iid is None:
        return None
    token = str(iid).strip()
    if not token:
        return None
    attempts_raw = payload.get("attempts")
    try:
        attempts = int(attempts_raw)
    except (TypeError, ValueError):
        attempts = 0
    attempts = max(0, attempts)
    pending: dict[str, Any] = {
        "kind": DROP_KIND_WEAPON,
        "iid": token,
        "attempts": attempts,
    }
    last_roll = payload.get("last_roll")
    try:
        pending["last_roll"] = int(last_roll)
    except (TypeError, ValueError):
        pass
    return pending


def _is_broken_armour(monster: Mapping[str, Any]) -> bool:
    armour = monster.get("armour_slot")
    if not isinstance(armour, Mapping):
        return False
    item_id = armour.get("item_id")
    return str(item_id) == itemsreg.BROKEN_ARMOUR_ID


def _current_weapon_entry(monster: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    wielded = monster.get("wielded")
    if not isinstance(wielded, str) or not wielded:
        return None
    bag = monster.get("bag")
    if not isinstance(bag, list):
        return None
    for entry in bag:
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("iid")) != wielded:
            continue
        return entry
    return None


def _is_broken_weapon_entry(entry: Mapping[str, Any]) -> bool:
    item_id = str(entry.get("item_id") or "")
    if item_id != itemsreg.BROKEN_WEAPON_ID:
        return False
    enchant = entry.get("enchant_level")
    try:
        level = int(enchant)
    except (TypeError, ValueError):
        level = 0
    return level <= 0


def _drop_armour(monster: MutableMapping[str, Any], ctx: MutableMapping[str, Any]) -> bool:
    armour = monster.get("armour_slot")
    if not isinstance(armour, MutableMapping):
        return False
    iid = armour.get("iid")
    if not iid:
        return False
    pos = _resolve_pos(monster)
    if pos is None:
        return False
    dropped = combat_loot.drop_existing_iids([str(iid)], pos)
    if not dropped:
        return False
    monster["armour_slot"] = None
    _refresh_monster(monster)
    _mark_monsters_dirty(ctx, monster)
    catalog = _load_catalog()
    inst = itemsreg.get_instance(str(iid)) or {"item_id": itemsreg.BROKEN_ARMOUR_ID}
    label = item_display.item_label(inst, catalog.get(str(inst.get("item_id"))) or {}, show_charges=False)
    bus = ctx.get("feedback_bus") if isinstance(ctx, Mapping) else None
    if hasattr(bus, "push"):
        monster_label = _monster_display_name(monster)
        message = textutils.render_feedback_template(
            textutils.TEMPLATE_MONSTER_DROP,
            monster=monster_label,
            item=label,
        )
        bus.push(
            "COMBAT/INFO",
            message,
            template=textutils.TEMPLATE_MONSTER_DROP,
            monster=monster_label,
            item=label,
        )
    turnlog.emit(
        ctx,
        "AI/INVENTORY/DROP_ARMOUR",
        monster=_monster_id(monster),
        iid=str(iid),
        pos=pos,
    )
    return True


def _remove_bag_entry(monster: MutableMapping[str, Any], iid: str) -> MutableMapping[str, Any] | None:
    bag = monster.get("bag")
    if not isinstance(bag, list):
        return None
    for entry in list(bag):
        if not isinstance(entry, MutableMapping):
            continue
        if str(entry.get("iid")) == iid:
            bag.remove(entry)
            return entry
    return None


def _drop_weapon(monster: MutableMapping[str, Any], ctx: MutableMapping[str, Any], iid: str) -> bool:
    entry = _remove_bag_entry(monster, iid)
    if entry is None:
        return False
    pos = _resolve_pos(monster)
    if pos is None:
        return False
    dropped = combat_loot.drop_existing_iids([iid], pos)
    if not dropped:
        # put entry back if drop failed
        bag = monster.setdefault("bag", [])
        if isinstance(bag, list):
            bag.append(entry)
        return False
    if monster.get("wielded") == iid:
        monster["wielded"] = None
    _refresh_monster(monster)
    _mark_monsters_dirty(ctx, monster)
    catalog = _load_catalog()
    inst = itemsreg.get_instance(iid) or {"item_id": entry.get("item_id")}
    tpl = catalog.get(str(inst.get("item_id"))) or {}
    name = item_display.item_label(inst, tpl, show_charges=False)
    bus = ctx.get("feedback_bus") if isinstance(ctx, Mapping) else None
    if hasattr(bus, "push"):
        monster_label = _monster_display_name(monster)
        message = textutils.render_feedback_template(
            textutils.TEMPLATE_MONSTER_DROP,
            monster=monster_label,
            item=name,
        )
        bus.push(
            "COMBAT/INFO",
            message,
            template=textutils.TEMPLATE_MONSTER_DROP,
            monster=monster_label,
            item=name,
        )
    turnlog.emit(
        ctx,
        "AI/INVENTORY/DROP_WEAPON",
        monster=_monster_id(monster),
        iid=iid,
        pos=pos,
    )
    return True


def schedule_weapon_drop(monster: MutableMapping[str, Any], weapon_iid: str) -> None:
    if not isinstance(monster, MutableMapping):
        return
    iid = str(weapon_iid or "").strip()
    if not iid:
        return
    entry = _current_weapon_entry(monster)
    if not entry or str(entry.get("iid")) != iid:
        return
    if not _is_broken_weapon_entry(entry):
        return
    state = _ai_state(monster)
    pending = _normalize_pending(state.get("pending_drop"))
    if pending and pending.get("iid") == iid:
        return
    state["pending_drop"] = {"kind": DROP_KIND_WEAPON, "iid": iid, "attempts": 0}


def process_pending_drops(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random | None,
) -> dict[str, Any]:
    """Resolve cracked gear drops before the action cascade."""

    result = {"armour": False, "weapon": False, "attempted_weapon": False}

    if not isinstance(monster, MutableMapping):
        return result

    if rng is None:
        rng = random.Random()

    # Immediate armour drop if present.
    if _is_broken_armour(monster):
        if _drop_armour(monster, ctx):
            result["armour"] = True

    state = _ai_state(monster)
    pending = _normalize_pending(state.get("pending_drop"))

    current_entry = _current_weapon_entry(monster)
    if current_entry and _is_broken_weapon_entry(current_entry):
        if not pending:
            pending = {"kind": DROP_KIND_WEAPON, "iid": str(current_entry.get("iid")), "attempts": 0}
            state["pending_drop"] = pending
    else:
        if "pending_drop" in state:
            state.pop("pending_drop", None)
        return result

    if not pending:
        return result

    roll = int(rng.randrange(100))
    pending["attempts"] = int(pending.get("attempts", 0)) + 1
    pending["last_roll"] = roll
    result["attempted_weapon"] = True
    if roll < WEAPON_DROP_CHANCE:
        succeeded = _drop_weapon(monster, ctx, pending["iid"])
        if succeeded:
            state.pop("pending_drop", None)
            result["weapon"] = True
        else:
            state["pending_drop"] = pending
    else:
        state["pending_drop"] = pending
    return result


__all__ = ["process_pending_drops", "schedule_weapon_drop", "WEAPON_DROP_CHANCE"]
