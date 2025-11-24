from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from mutants.registries import items_catalog as catreg
from mutants.registries import items_instances as itemsreg
from mutants.services import player_state as pstate
from mutants.state import state_path


_LOGGER: logging.Logger | None = None
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUPS = 3


def _debug_enabled() -> bool:
    raw = os.getenv("MUTANTS_STATE_DEBUG")
    if raw is None:
        return True
    token = raw.strip().lower()
    if token in {"0", "false", "off"}:
        return False
    return True


def _state_logger() -> logging.Logger | None:
    global _LOGGER

    if not _debug_enabled():
        return None

    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger("mutants.state")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_path = state_path("logs", "game.log")
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUPS,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(logging.Formatter("%(asctime)s STATE %(message)s"))
    logger.addHandler(handler)

    _LOGGER = logger
    return logger


def _serialize_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False)


def _emit(payload: Mapping[str, Any]) -> None:
    logger = _state_logger()
    if logger is None:
        return

    parts = []
    for key, value in payload.items():
        if value is None:
            continue
        parts.append(f"{key}={_serialize_value(value)}")
    if parts:
        logger.info(" ".join(parts))


def _canonical_pos(state: Mapping[str, Any] | None) -> tuple[int, int, int] | None:
    if state is None:
        return None
    try:
        year, x, y = pstate.canonical_player_pos(state)
    except Exception:
        return None
    return int(year), int(x), int(y)


def _view_pos(ctx: Mapping[str, Any] | None, state: Mapping[str, Any] | None) -> list[int] | None:
    view: Any = None
    if isinstance(ctx, Mapping):
        view = ctx.get("_active_view") or ctx.get("active_view")
    if view is None and isinstance(state, Mapping):
        view = state.get("active")
    if isinstance(view, Mapping):
        pos = view.get("pos")
    else:
        pos = None
    if isinstance(pos, Iterable):
        vals = list(pos)
        try:
            return [int(vals[0]), int(vals[1]), int(vals[2])]
        except Exception:
            return None
    return None


def _active_state(ctx: Any, state: Mapping[str, Any] | None = None) -> Mapping[str, Any] | None:
    if isinstance(state, Mapping):
        return state
    if isinstance(ctx, Mapping):
        candidate = ctx.get("player_state")
        if isinstance(candidate, Mapping):
            return candidate
    return None


def _base_context(
    ctx: Any, state: Mapping[str, Any] | None = None, *, player: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    active_state = _active_state(ctx, state)
    canonical = _canonical_pos(player or active_state)
    view = _view_pos(ctx if isinstance(ctx, Mapping) else None, active_state)
    klass = None
    active_id = None
    if isinstance(player, Mapping):
        klass = player.get("class") or player.get("name")
        active_id = player.get("id")
    if klass is None and isinstance(active_state, Mapping):
        try:
            klass = pstate.get_active_class(active_state)
        except Exception:
            klass = None
        active_id = active_state.get("active_id")

    payload: dict[str, Any] = {}
    if klass:
        payload["class"] = klass
    if active_id is not None:
        payload["active_id"] = active_id
    if canonical:
        year, x, y = canonical
        payload["year"] = year
        payload["pos"] = [x, y]
        payload["pos3"] = [year, x, y]
    if view:
        payload["view_pos"] = view
    return payload


def _inventory_snapshot(player: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(player, Mapping):
        return []
    inv = player.get("inventory")
    inventory = [str(i) for i in inv] if isinstance(inv, Iterable) else []
    catalog = catreg.load_catalog() or {}
    snapshot: list[dict[str, Any]] = []
    for iid in inventory:
        inst = itemsreg.get_instance(iid) or {}
        item_id = (
            inst.get("item_id")
            or inst.get("catalog_id")
            or inst.get("id")
            or inst.get("display_name")
            or iid
        )
        template = catalog.get(str(item_id)) if isinstance(catalog, Mapping) else None
        if isinstance(template, Mapping):
            name = template.get("display") or template.get("name") or template.get("title")
        else:
            name = None
        snapshot.append({"iid": iid, "name": str(name or item_id)})
    return snapshot


def _equipment_snapshot(player: Mapping[str, Any] | None) -> dict[str, Any]:
    armour = pstate.get_equipped_armour_id(player or {}) if isinstance(player, Mapping) else None
    details: dict[str, Any] = {}
    if armour:
        details["armour"] = _describe_iid(armour)
    if not details:
        return {}
    return details


def log_tick(ctx: Any, tick: int) -> None:
    payload = {"event": "tick", "tick": int(tick)}
    payload.update(_base_context(ctx))
    _emit(payload)


def log_pos_drift(
    ctx: Any,
    *,
    canonical: Sequence[Any] | None,
    view: Sequence[Any] | None,
    state: Mapping[str, Any] | None = None,
) -> None:
    active_state = _active_state(ctx, state)
    players: list[dict[str, Any]] = []
    if isinstance(active_state, Mapping):
        entries = active_state.get("players")
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                pos = entry.get("pos") if isinstance(entry.get("pos"), Iterable) else None
                pos_vec = None
                if pos:
                    vec = list(pos)
                    if len(vec) >= 3:
                        try:
                            pos_vec = [int(vec[0]), int(vec[1]), int(vec[2])]
                        except Exception:
                            pos_vec = None
                players.append(
                    {
                        "class": entry.get("class") or entry.get("name"),
                        "id": entry.get("id"),
                        "pos": pos_vec,
                    }
                )

    payload = {"event": "pos_drift", "canonical_pos": list(canonical) if canonical else None}
    if view:
        payload["view_pos"] = list(view)
    if players:
        payload["players"] = players
    payload.update(_base_context(ctx, active_state))
    _emit(payload)


def _summaries_from_state(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    players = state.get("players") if isinstance(state, Mapping) else None
    if isinstance(players, list):
        for entry in players:
            if not isinstance(entry, Mapping):
                continue
            pos = entry.get("pos") if isinstance(entry.get("pos"), Iterable) else None
            pos_vec = None
            if pos:
                vec = list(pos)
                if len(vec) >= 3:
                    try:
                        pos_vec = [int(vec[0]), int(vec[1]), int(vec[2])]
                    except Exception:
                        pos_vec = None
            inv = entry.get("inventory") if isinstance(entry.get("inventory"), list) else []
            summaries.append(
                {
                    "class": entry.get("class") or entry.get("name"),
                    "id": entry.get("id"),
                    "pos": pos_vec,
                    "year": pos_vec[0] if isinstance(pos_vec, list) and len(pos_vec) >= 1 else None,
                    "ions": entry.get("ions"),
                    "inventory_size": len(inv),
                }
            )
    return summaries


def log_load_state(state: Mapping[str, Any], *, source: str | None = None) -> None:
    payload = {
        "event": "load_state",
        "source": source,
        "players": _summaries_from_state(state),
    }
    payload.update(_base_context(None, state))
    _emit(payload)


def log_save_state(state: Mapping[str, Any], *, reason: str | None = None) -> None:
    payload = {
        "event": "save_state",
        "reason": reason,
        "players": _summaries_from_state(state),
    }
    payload.update(_base_context(None, state))
    _emit(payload)


def log_save_failure(
    *,
    reason: str | None = None,
    path: str | Path | None = None,
    tmp_path: str | None = None,
    error: BaseException | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "save_state_error",
        "reason": reason,
        "path": str(path) if path is not None else None,
        "tmp_path": tmp_path,
    }
    if error is not None:
        payload.update(
            {
                "exc_type": type(error).__name__,
                "errno": getattr(error, "errno", None),
                "message": str(error),
            }
        )
    payload.update(_base_context(None, None))
    _emit(payload)


def log_inventory_stage(
    ctx: Any,
    player: Mapping[str, Any] | None,
    *,
    command: str,
    arg: Any = None,
    stage: str,
    extra: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    snapshot = _inventory_snapshot(player)
    equipment = _equipment_snapshot(player)
    payload = {"event": stage, "command": command}
    if arg is not None:
        payload["arg"] = arg
    payload["inventory"] = snapshot
    if equipment:
        payload["equipment"] = equipment
    payload.update(_base_context(ctx, player, player=player))
    if isinstance(extra, Mapping):
        payload.update({k: v for k, v in extra.items()})
    _emit(payload)
    return [{"inventory": snapshot, "equipment": equipment}]


def log_inventory_update(
    ctx: Any,
    player: Mapping[str, Any] | None,
    *,
    command: str,
    arg: Any = None,
    before: Sequence[Mapping[str, Any]] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    after_inv = _inventory_snapshot(player)
    after_equipment = _equipment_snapshot(player)
    before_inv: list[Mapping[str, Any]] | None = None
    before_equipment: Mapping[str, Any] | None = None
    if before:
        if isinstance(before, Sequence) and len(before) == 1 and isinstance(before[0], Mapping):
            before_inv = before[0].get("inventory") if isinstance(before[0], Mapping) else None
            before_equipment = before[0].get("equipment") if isinstance(before[0], Mapping) else None
        elif isinstance(before, Sequence):
            before_inv = [dict(entry) for entry in before if isinstance(entry, Mapping)]
    payload = {
        "event": "inventory_update",
        "command": command,
        "arg": arg,
        "before": before_inv,
        "after": after_inv,
        "equipment_before": before_equipment,
        "equipment_after": after_equipment,
    }
    payload.update(_base_context(ctx, player, player=player))
    if isinstance(extra, Mapping):
        payload.update({k: v for k, v in extra.items()})
        for key, value in extra.items():
            if isinstance(key, str) and key.endswith("_iid") and value:
                payload[f"{key}_detail"] = _describe_iid(value)
        swapped = extra.get("swapped") if isinstance(extra, Mapping) else None
        if swapped:
            payload["swapped_detail"] = _describe_iid(swapped)
    _emit(payload)


def _describe_iid(iid: Any) -> dict[str, Any]:
    if iid is None:
        return {}
    inst = itemsreg.get_instance(iid) or {}
    item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id") or iid
    catalog = catreg.load_catalog() or {}
    template = catalog.get(str(item_id)) if isinstance(catalog, Mapping) else None
    if isinstance(template, Mapping):
        name = template.get("display") or template.get("name") or template.get("title")
    else:
        name = None
    return {"iid": iid, "item_id": item_id, "name": name or item_id}


def log_travel(
    ctx: Any,
    *,
    command: str,
    arg: Any,
    from_pos: Sequence[Any],
    to_pos: Sequence[Any],
    ions_before: Any,
    ions_after: Any,
    extra: Mapping[str, Any] | None = None,
) -> None:
    payload = {
        "event": command,
        "arg": arg,
        "from_pos": list(from_pos),
        "to_pos": list(to_pos),
        "from_year": int(from_pos[0]) if from_pos else None,
        "to_year": int(to_pos[0]) if to_pos else None,
        "ions_before": ions_before,
        "ions_after": ions_after,
    }
    payload.update(_base_context(ctx))
    if isinstance(extra, Mapping):
        payload.update({k: v for k, v in extra.items()})
    _emit(payload)


def log_monster_spawn(monster: Mapping[str, Any], *, reason: str | None = None) -> None:
    if not isinstance(monster, Mapping):
        return
    payload = {
        "event": "monster_spawn",
        "reason": reason,
        "id": monster.get("id") or monster.get("instance_id"),
        "monster_id": monster.get("monster_id"),
        "name": monster.get("name"),
        "pos": monster.get("pos") if isinstance(monster.get("pos"), Iterable) else None,
    }
    _emit(payload)


def log_monster_despawn(
    monster: Mapping[str, Any] | None, *, reason: str | None = None, drops: Iterable[Any] | None = None
) -> None:
    payload = {
        "event": "monster_despawn",
        "reason": reason,
    }
    if isinstance(monster, Mapping):
        payload.update(
            {
                "id": monster.get("id") or monster.get("instance_id"),
                "monster_id": monster.get("monster_id"),
                "name": monster.get("name"),
                "pos": monster.get("pos") if isinstance(monster.get("pos"), Iterable) else None,
            }
        )
    if drops:
        payload["drops"] = [_describe_iid(entry.get("iid")) if isinstance(entry, Mapping) else entry for entry in drops]
    _emit(payload)
