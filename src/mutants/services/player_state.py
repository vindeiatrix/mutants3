from __future__ import annotations
import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

from mutants.io.atomic import atomic_write_json
from mutants.registries import items_instances as itemsreg
from mutants.state import state_path
from mutants.services import monsters_state
from .equip_debug import _edbg_enabled, _edbg_log


LOG_P = logging.getLogger("mutants.playersdbg")


_PDBG_CONFIGURED = False


DEFAULT_PLAYER_DISPLAY_NAME = "Vindeiatrix"


_RUNTIME_PLAYER_KEY = "_runtime_player"


def _active_player_from_state(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the active player mapping from ``state``."""

    if not isinstance(state, Mapping):
        return {}

    players = state.get("players")
    active_id = state.get("active_id")
    if isinstance(players, list) and players:
        if active_id is not None:
            for player in players:
                if isinstance(player, MutableMapping) and player.get("id") == active_id:
                    return player  # type: ignore[return-value]
        first = players[0]
        if isinstance(first, MutableMapping):
            return first  # type: ignore[return-value]

    active = state.get("active")
    if isinstance(active, MutableMapping):
        return active  # type: ignore[return-value]

    return {}


def _load_player_from_disk() -> Dict[str, Any]:
    """Load and return the active player mapping from disk."""

    state = load_state()
    player = _active_player_from_state(state)
    if isinstance(player, MutableMapping):
        player.setdefault("_dirty", False)
        return player  # type: ignore[return-value]
    return {"_dirty": False}


def _strip_runtime_metadata(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Return ``state`` copied without transient runtime markers."""

    sanitized = copy.deepcopy(state if isinstance(state, Mapping) else {})

    active = sanitized.get("active")
    if isinstance(active, MutableMapping):
        active.pop("_dirty", None)

    players = sanitized.get("players")
    if isinstance(players, list):
        for entry in players:
            if isinstance(entry, MutableMapping):
                entry.pop("_dirty", None)

    return sanitized


def _save_player_to_disk(state: Mapping[str, Any]) -> None:
    """Persist ``state`` to disk using the canonical saver."""

    save_state(dict(state))


def _current_runtime_ctx() -> MutableMapping[str, Any] | None:
    """Return the current runtime context if available."""

    try:
        from mutants.app import context as app_context

        ctx = app_context.current_context()
    except Exception:
        return None

    return ctx if isinstance(ctx, MutableMapping) else None


def ensure_player_state(ctx: MutableMapping[str, Any]) -> Dict[str, Any]:
    """Return the runtime player for ``ctx``, loading it if required."""

    if not isinstance(ctx, MutableMapping):
        return _load_player_from_disk()

    cached = ctx.get(_RUNTIME_PLAYER_KEY)
    if isinstance(cached, MutableMapping):
        cached.setdefault("_dirty", False)
        return cached  # type: ignore[return-value]

    state_hint = ctx.get("player_state")
    if not isinstance(state_hint, MutableMapping):
        state_hint = load_state()
        ctx["player_state"] = state_hint

    active_player = _active_player_from_state(state_hint)
    if not isinstance(active_player, MutableMapping):
        active_player = {}
        state_hint["active"] = active_player

    active_player.setdefault("_dirty", False)
    ctx[_RUNTIME_PLAYER_KEY] = active_player
    return active_player  # type: ignore[return-value]


def save_player_state(ctx: MutableMapping[str, Any]) -> None:
    """Persist the runtime player associated with ``ctx`` if dirty."""

    if not isinstance(ctx, MutableMapping):
        return

    player = ctx.get(_RUNTIME_PLAYER_KEY)
    if not isinstance(player, MutableMapping):
        return

    if not player.get("_dirty"):
        return

    state = ctx.get("player_state")
    if not isinstance(state, Mapping):
        state = load_state()

    sanitized = _strip_runtime_metadata(state)
    _save_player_to_disk(sanitized)

    ctx["player_state"] = sanitized
    _, refreshed_player = get_active_pair(sanitized)
    refreshed_player.setdefault("_dirty", False)
    ctx[_RUNTIME_PLAYER_KEY] = refreshed_player


def _combat_log_set(target: Optional[str], actor: Optional[str]) -> None:
    if not _pdbg_enabled() or not target:
        return
    try:
        _pdbg_setup_file_logging()
        LOG_P.info("COMBAT/SET target=%s by=%s", target, actor or "?")
    except Exception:  # pragma: no cover - debug logging
        pass


def _combat_log_clear(reason: str) -> None:
    if not _pdbg_enabled():
        return
    try:
        _pdbg_setup_file_logging()
        LOG_P.info("COMBAT/CLEAR reason=%s", reason)
    except Exception:  # pragma: no cover - debug logging
        pass

_STAT_KEYS: Tuple[str, ...] = ("str", "int", "wis", "dex", "con", "cha")
_IONS_KEYS: Tuple[str, ...] = ("ions", "Ions")
_RIBLETS_KEYS: Tuple[str, ...] = ("riblets", "Riblets")
_EXP_KEYS: Tuple[str, ...] = (
    "exp_points",
    "experience_points",
    "experience",
    "ExpPoints",
    "ExperiencePoints",
)
_LEVEL_KEYS: Tuple[str, ...] = ("level", "Level")


def _empty_stats() -> Dict[str, int]:
    return {key: 0 for key in _STAT_KEYS}


def _empty_hp() -> Dict[str, int]:
    return {"current": 0, "max": 0}


def _pdbg_setup_file_logging() -> None:
    """Send playersdbg logs to a file when debugging is enabled."""

    global _PDBG_CONFIGURED
    if _PDBG_CONFIGURED or not _pdbg_enabled():
        return
    try:
        log_dir = state_path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "players_debug.log"
        if not any(
            isinstance(handler, logging.FileHandler)
            and getattr(handler, "baseFilename", None) == str(log_path)
            for handler in LOG_P.handlers
        ):
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s"))
            LOG_P.addHandler(handler)
        LOG_P.setLevel(logging.INFO)
        LOG_P.propagate = False
        _PDBG_CONFIGURED = True
    except Exception:  # pragma: no cover - defensive logging only
        pass


def _pdbg_enabled() -> bool:
    return bool(os.environ.get("PLAYERS_DEBUG") or os.environ.get("WORLD_DEBUG"))


def _playersdbg_log(action: str, state: Dict[str, Any]) -> None:
    if not _pdbg_enabled() or not isinstance(state, dict):
        return
    _pdbg_setup_file_logging()
    try:
        active = state.get("active")
        if not isinstance(active, dict):
            active = {}
        klass = active.get("class") or state.get("class") or "?"

        raw_inv = state.get("inventory")
        if not isinstance(raw_inv, list):
            raw_inv = active.get("inventory") if isinstance(active, dict) else None
        inventory: List[str] = [str(i) for i in raw_inv or [] if i is not None]

        ions_map: Dict[str, int] = {}
        raw_ions = state.get("ions_by_class")
        if isinstance(raw_ions, dict):
            ions_map = {
                str(name): _coerce_int(amount, 0)
                for name, amount in raw_ions.items()
                if isinstance(name, str) and name
            }

        rib_map: Dict[str, int] = {}
        raw_riblets = state.get("riblets_by_class")
        if isinstance(raw_riblets, dict):
            rib_map = {
                str(name): _coerce_int(amount, 0)
                for name, amount in raw_riblets.items()
                if isinstance(name, str) and name
            }

        active_ions = ions_map.get(klass, _coerce_int(state.get("Ions", state.get("ions")), 0))
        active_riblets = rib_map.get(klass, _coerce_int(state.get("Riblets", state.get("riblets")), 0))

        LOG_P.info(
            "[playersdbg] %s path=%s class=%s inv_iids=%s pos=%s ions=%s riblets=%s ions_map=%s riblets_map=%s",
            action,
            str(_player_path()),
            klass,
            inventory,
            active.get("pos"),
            active_ions,
            active_riblets,
            ions_map,
            rib_map,
        )
    except Exception:  # pragma: no cover - defensive logging only
        pass

def _player_path() -> Path:
    return state_path("playerlivestate.json")


def _sanitize_player_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        return token or None
    try:
        token = str(value).strip()
    except Exception:
        return None
    return token or None


def _coerce_display_name(value: Any) -> Optional[str]:
    if isinstance(value, str):
        token = value.strip()
        return token or None
    return None


def _extract_display_name(payload: Mapping[str, Any] | None) -> Optional[str]:
    if not isinstance(payload, Mapping):
        return None
    for key in ("display_name", "name"):
        candidate = _coerce_display_name(payload.get(key))
        if candidate:
            return candidate
    return None


def _persist_canonical(state: Dict[str, Any]) -> None:
    """Write ``state`` to disk without mutating logging state."""

    atomic_write_json(_player_path(), state)


def _has_profile_payload(state: Dict[str, Any]) -> bool:
    """Return True if ``state`` appears to represent a single-player profile."""

    for key in ("active", "inventory", "bags", "class", "name", "year"):
        if key in state:
            return True
    return False


def _coerce_int(value: Any, default: int = 0) -> int:
    """Best-effort conversion of ``value`` to ``int`` with ``default`` fallback."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sanitize_class_int(value: Any, default: int) -> int:
    """Return ``value`` coerced to ``int`` honoring ``default`` domain rules."""

    sanitized = _coerce_int(value, default)
    if default <= 0:
        return max(0, sanitized)
    if default == 1:
        return max(1, sanitized)
    return sanitized


def get_player_display_name(
    state: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return a best-effort display name for the active player."""

    state_mapping: Mapping[str, Any] | None
    if isinstance(state, Mapping):
        state_mapping = state
    else:
        try:
            state_mapping = load_state()
        except Exception:
            state_mapping = None

    if not isinstance(state_mapping, Mapping):
        return DEFAULT_PLAYER_DISPLAY_NAME

    players = state_mapping.get("players")
    active_id = state_mapping.get("active_id")
    if isinstance(players, list):
        active_entry: Optional[Mapping[str, Any]] = None
        if active_id is not None:
            for entry in players:
                if not isinstance(entry, Mapping):
                    continue
                if entry.get("id") == active_id:
                    active_entry = entry
                    break
        if active_entry is None and players:
            first = players[0]
            active_entry = first if isinstance(first, Mapping) else None
        if active_entry:
            name = _extract_display_name(active_entry)
            if name:
                return name
        for entry in players:
            name = _extract_display_name(entry if isinstance(entry, Mapping) else None)
            if name:
                return name

    active_block = state_mapping.get("active")
    name = _extract_display_name(active_block if isinstance(active_block, Mapping) else None)
    if name:
        return name

    name = _extract_display_name(state_mapping)
    if name:
        return name

    return DEFAULT_PLAYER_DISPLAY_NAME


def _snapshot_currency_map(payload: Any) -> Dict[str, int]:
    """Return a sanitized snapshot of a currency mapping."""

    if not isinstance(payload, dict):
        return {}
    snapshot: Dict[str, int] = {}
    for name, amount in payload.items():
        if not isinstance(name, str) or not name:
            continue
        snapshot[name] = _coerce_int(amount, 0)
    return snapshot


def _invariants_summary(state: Dict[str, Any], details: Optional[Dict[str, Any]] = None) -> str:
    """Return a compact description of critical player-state invariants."""

    active = state.get("active") if isinstance(state, dict) else {}
    if not isinstance(active, dict):
        active = {}
    klass = active.get("class") or state.get("class") or "?"
    pos = active.get("pos")

    bags = state.get("bags") if isinstance(state, dict) else None
    if isinstance(bags, dict):
        bag_counts = {
            str(name): len(contents) if isinstance(contents, list) else -1
            for name, contents in bags.items()
        }
    else:
        bag_counts = {}

    inventory = state.get("inventory") if isinstance(state, dict) else None
    if isinstance(inventory, list):
        inv_count = len(inventory)
    else:
        inv_count = -1

    ions = _snapshot_currency_map(state.get("ions_by_class") if isinstance(state, dict) else {})
    riblets = _snapshot_currency_map(state.get("riblets_by_class") if isinstance(state, dict) else {})

    map_counts: Dict[str, int] = {}
    payload = state if isinstance(state, dict) else {}
    for key in (
        "stats_by_class",
        "hp_by_class",
        "exp_by_class",
        "level_by_class",
        "ions_by_class",
        "riblets_by_class",
    ):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, dict):
            map_counts[key] = len(value)
        else:
            map_counts[key] = 0

    if isinstance(details, dict):
        extra_counts = details.get("map_counts")
        if isinstance(extra_counts, dict):
            map_counts.update({k: int(v) for k, v in extra_counts.items()})

    return (
        f"class={klass} pos={pos} inv_count={inv_count} "
        f"bag_counts={bag_counts} ions={ions} riblets={riblets} "
        f"map_counts={map_counts}"
    )


def _check_invariants_and_log(state: Dict[str, Any], where: str) -> None:
    """Emit diagnostic logs describing whether invariants hold for ``state``."""

    if not _pdbg_enabled():
        return

    _pdbg_setup_file_logging()
    try:
        ok, details = _evaluate_invariants_with_details(state)
    except Exception as exc:
        ok = False
        details = {"error": repr(exc)}

    summary = _invariants_summary(state if isinstance(state, dict) else {}, details)
    extra = ""
    if isinstance(details, dict):
        if details.get("failure"):
            extra += f" failure={details['failure']}"
        if details.get("missing_pair"):
            missing_map, missing_class = details["missing_pair"]
            extra += f" missing={missing_map}:{missing_class}"
        if details.get("mirror_mismatch"):
            extra += f" mirror={details['mirror_mismatch']}"
        if details.get("active_mismatch"):
            extra += f" active={details['active_mismatch']}"
        if details.get("hp_violation"):
            cls_name, cur, max_val = details["hp_violation"]
            extra += f" hp={cls_name}:{cur}>{max_val}"
        if details.get("error") and "error" not in extra:
            extra += f" error={details['error']}"

    if ok:
        LOG_P.info("[playersdbg] INV-OK %s :: %s", where, summary)
    else:
        LOG_P.error("[playersdbg] INV-FAIL %s :: %s%s", where, summary, extra)


def _normalize_class_name(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def normalize_class_name(value: Any) -> Optional[str]:
    """Public wrapper returning a sanitized class token or ``None``."""

    return _normalize_class_name(value)


def _evaluate_item_instance_invariants() -> Tuple[bool, Dict[str, Any]]:
    summary: Dict[str, Any] = {}

    try:
        snapshot = itemsreg.snapshot_instances()
    except Exception as exc:  # pragma: no cover - defensive only
        summary["error"] = repr(exc)
        return False, summary

    summary["count"] = len(snapshot)
    invalid_levels: List[str] = []
    missing_condition: List[str] = []
    stray_condition: List[str] = []

    broken_ids = {itemsreg.BROKEN_WEAPON_ID, itemsreg.BROKEN_ARMOUR_ID}

    for inst in snapshot:
        iid_raw = inst.get("instance_id") or inst.get("iid") or inst.get("item_id")
        iid = str(iid_raw) if iid_raw is not None else "<unknown>"

        try:
            level_val = int(inst.get("enchant_level", 0))
        except (TypeError, ValueError):
            level_val = -1
        if level_val < 0:
            invalid_levels.append(iid)

        item_id_raw = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
        item_id = str(item_id_raw) if item_id_raw is not None else ""
        broken = item_id in broken_ids
        has_condition = "condition" in inst

        if broken and has_condition:
            stray_condition.append(iid)
        if not broken and not has_condition:
            missing_condition.append(iid)

    if invalid_levels:
        summary["invalid_enchant_count"] = len(invalid_levels)
        summary["invalid_enchant_sample"] = invalid_levels[:5]
    if missing_condition:
        summary["missing_condition_count"] = len(missing_condition)
        summary["missing_condition_sample"] = missing_condition[:5]
    if stray_condition:
        summary["broken_condition_count"] = len(stray_condition)
        summary["broken_condition_sample"] = stray_condition[:5]

    ok = not (invalid_levels or missing_condition or stray_condition)
    return ok, summary


def _gather_class_sources(
    state: Dict[str, Any], klass: str, active: Dict[str, Any]
) -> Tuple[Iterable[str], Dict[str, Dict[str, Any]]]:
    classes: List[str] = []
    sources: Dict[str, Dict[str, Any]] = {}

    players = state.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, dict):
                continue
            candidate = (
                _normalize_class_name(player.get("class"))
                or _normalize_class_name(player.get("name"))
            )
            if not candidate:
                continue
            if candidate not in sources:
                sources[candidate] = player
            classes.append(candidate)

    active_class = _normalize_class_name(active.get("class")) if isinstance(active, dict) else None
    fallback_class = _normalize_class_name(klass) or active_class
    if fallback_class:
        classes.append(fallback_class)
        if fallback_class not in sources and isinstance(active, dict):
            sources[fallback_class] = active

    root_candidates = (
        _normalize_class_name(state.get("class")),
        _normalize_class_name(state.get("name")),
    )
    for candidate in root_candidates:
        if candidate and candidate not in sources and isinstance(active, dict):
            sources[candidate] = active
        if candidate:
            classes.append(candidate)

    if not classes:
        classes.append("Thief")

    unique_classes = []
    seen: set[str] = set()
    for cls_name in classes:
        if cls_name not in seen:
            unique_classes.append(cls_name)
            seen.add(cls_name)

    return unique_classes, sources


def _source_candidates_for_class(
    cls_name: str,
    class_sources: Dict[str, Dict[str, Any]],
    active: Dict[str, Any],
    state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    primary = class_sources.get(cls_name)
    if isinstance(primary, dict):
        candidates.append(primary)
    if isinstance(active, dict) and active is not primary:
        candidates.append(active)
    if state is not primary and state is not active:
        candidates.append(state)
    return candidates


def _extract_scalar(
    sources: Iterable[Dict[str, Any]], keys: Iterable[str]
) -> Optional[Any]:
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in keys:
            if key in src:
                return src[key]
    return None


def _normalize_hp_block(payload: Any) -> Dict[str, int]:
    current = 0
    maximum = 0
    if isinstance(payload, dict):
        current = max(0, _coerce_int(payload.get("current"), 0))
        max_raw = payload.get("max")
        if max_raw is None:
            max_raw = current
        maximum = max(0, _coerce_int(max_raw, current))
        if current > maximum:
            current = maximum
    else:
        current = 0
        maximum = 0
    return {"current": current, "max": maximum}


def _normalize_stats_block(payload: Any) -> Dict[str, int]:
    normalized = _empty_stats()
    if isinstance(payload, Mapping):
        for key in _STAT_KEYS:
            normalized[key] = _coerce_int(payload.get(key), 0)
    return normalized


def _string_key(value: Any) -> Optional[str]:
    if isinstance(value, str):
        candidate = value
    elif value is None:
        return None
    else:
        try:
            candidate = str(value)
        except Exception:
            return None
    candidate = candidate.strip() if isinstance(candidate, str) else candidate
    if not candidate:
        return None
    return candidate


def _sanitize_spell_list(payload: Any) -> List[str]:
    if not isinstance(payload, list):
        return []
    deduped: List[str] = []
    seen: set[str] = set()
    for item in payload:
        if isinstance(item, str) and item:
            key = item
        elif item is None:
            continue
        else:
            key = _string_key(item) or ""
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _sanitize_spell_container(payload: Any) -> Dict[str, List[str]]:
    container: Dict[str, List[str]] = {"known": [], "prepared": []}
    if isinstance(payload, Mapping):
        container["known"] = _sanitize_spell_list(payload.get("known"))
        container["prepared"] = _sanitize_spell_list(payload.get("prepared"))
    return container


def _sanitize_effect_dict(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    sanitized: Dict[str, Any] = {}
    for key, value in payload.items():
        key_str = _string_key(key)
        if not key_str:
            continue
        sanitized[key_str] = value
    return sanitized


def _sanitize_spell_effect_entry(payload: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(payload, Mapping):
        personal_payload = payload.get("personal")
    else:
        personal_payload = None
    return {"personal": _sanitize_effect_dict(personal_payload)}


def _sanitize_world_tile_effects(payload: Any) -> Dict[str, Any]:
    return _sanitize_effect_dict(payload)


def _empty_migration_snapshot() -> Dict[str, Optional[Any]]:
    return {
        "ions": None,
        "riblets": None,
        "exp": None,
        "level": None,
        "hp": None,
        "stats": None,
        "wielded": None,
        "ready_target": None,
    }


def _capture_legacy_payload(
    snapshots: Dict[str, Dict[str, Optional[Any]]], cls_name: Optional[str], payload: Any
) -> None:
    if not cls_name or not isinstance(payload, Mapping):
        return

    snapshot = snapshots.setdefault(cls_name, _empty_migration_snapshot())

    if snapshot["ions"] is None:
        for key in _IONS_KEYS:
            if key in payload:
                snapshot["ions"] = _sanitize_class_int(payload.get(key), 0)
                break

    if snapshot["riblets"] is None:
        for key in _RIBLETS_KEYS:
            if key in payload:
                snapshot["riblets"] = _sanitize_class_int(payload.get(key), 0)
                break

    if snapshot["exp"] is None:
        for key in _EXP_KEYS:
            if key in payload:
                snapshot["exp"] = _sanitize_class_int(payload.get(key), 0)
                break

    if snapshot["level"] is None:
        for key in _LEVEL_KEYS:
            if key in payload:
                snapshot["level"] = _sanitize_class_int(payload.get(key), 1)
                break

    if snapshot["hp"] is None and "hp" in payload:
        snapshot["hp"] = _normalize_hp_block(payload.get("hp"))

    if snapshot["stats"] is None and "stats" in payload:
        stats_payload = payload.get("stats")
        if isinstance(stats_payload, Mapping):
            snapshot["stats"] = _normalize_stats_block(stats_payload)

    if snapshot["wielded"] is None:
        wield_map = payload.get("wielded_by_class")
        candidate: Any = None
        if isinstance(wield_map, Mapping):
            candidate = wield_map.get(cls_name)
        if candidate is None and "wielded" in payload:
            candidate = payload.get("wielded")
        if candidate is None and "weapon" in payload:
            candidate = payload.get("weapon")
        sanitized = _sanitize_equipped_iid(candidate)
        if sanitized:
            snapshot["wielded"] = sanitized

    if snapshot["ready_target"] is None:
        candidate: Any = None
        ready_map = payload.get("ready_target_by_class")
        if isinstance(ready_map, Mapping):
            candidate = ready_map.get(cls_name)
        target_map = payload.get("target_monster_id_by_class")
        if candidate is None and isinstance(target_map, Mapping):
            candidate = target_map.get(cls_name)
        if candidate is None and "ready_target" in payload:
            candidate = payload.get("ready_target")
        if candidate is None and "target_monster_id" in payload:
            candidate = payload.get("target_monster_id")
        sanitized_target = _sanitize_ready_target(candidate)
        if sanitized_target:
            snapshot["ready_target"] = sanitized_target


def _collect_legacy_snapshots(state: Dict[str, Any]) -> Dict[str, Dict[str, Optional[Any]]]:
    snapshots: Dict[str, Dict[str, Optional[Any]]] = {}

    players = state.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, dict):
                continue
            cls_name = (
                _normalize_class_name(player.get("class"))
                or _normalize_class_name(player.get("name"))
            )
            _capture_legacy_payload(snapshots, cls_name, player)

    active = state.get("active")
    if isinstance(active, dict):
        active_class = (
            _normalize_class_name(active.get("class"))
            or _normalize_class_name(active.get("name"))
        )
        _capture_legacy_payload(snapshots, active_class, active)

    root_class = _normalize_class_name(state.get("class")) or _normalize_class_name(
        state.get("name")
    )
    _capture_legacy_payload(snapshots, root_class, state)

    return snapshots


def _ensure_int_map(
    state: Dict[str, Any],
    key: str,
    fallback_keys: Tuple[str, ...],
    default: int,
    classes: Iterable[str],
    class_sources: Dict[str, Dict[str, Any]],
    active: Dict[str, Any],
    *,
    fill_missing: bool = True,
) -> Dict[str, int]:
    raw_map = state.get(key)
    normalized: Dict[str, int] = {}
    class_set = {cls for cls in classes if isinstance(cls, str) and cls}
    if isinstance(raw_map, dict):
        for name, value in raw_map.items():
            cls_name = _normalize_class_name(name)
            if not cls_name or cls_name not in class_set:
                continue
            normalized[cls_name] = _sanitize_class_int(value, default)

    for cls_name in classes:
        candidates = _source_candidates_for_class(cls_name, class_sources, active, state)
        fallback = _extract_scalar(candidates, fallback_keys)
        has_fallback = fallback is not None
        fallback_value = _sanitize_class_int(fallback, default)

        if cls_name in normalized:
            current_value = _sanitize_class_int(normalized[cls_name], default)
            if has_fallback and fallback_value != current_value:
                normalized[cls_name] = fallback_value
            else:
                normalized[cls_name] = current_value
            continue

        if not fill_missing:
            continue
        normalized[cls_name] = fallback_value

    state[key] = normalized
    return normalized


def _ensure_hp_map(
    state: Dict[str, Any],
    classes: Iterable[str],
    class_sources: Dict[str, Dict[str, Any]],
    active: Dict[str, Any],
) -> Dict[str, Dict[str, int]]:
    raw_map = state.get("hp_by_class")
    normalized: Dict[str, Dict[str, int]] = {}
    if isinstance(raw_map, dict):
        for name, payload in raw_map.items():
            cls_name = _normalize_class_name(name)
            if not cls_name:
                continue
            normalized[cls_name] = _normalize_hp_block(payload)

    for cls_name in classes:
        candidates = _source_candidates_for_class(cls_name, class_sources, active, state)
        block: Any = None
        for src in candidates:
            if not isinstance(src, dict):
                continue
            block = src.get("hp")
            if block is not None:
                break
        fallback_block = _normalize_hp_block(block)

        if cls_name in normalized:
            current_block = _normalize_hp_block(normalized[cls_name])
            if current_block == _empty_hp() and block is not None:
                normalized[cls_name] = fallback_block
            else:
                normalized[cls_name] = current_block
            continue

        normalized[cls_name] = fallback_block

    state["hp_by_class"] = normalized
    return normalized


def _ensure_stats_map(
    state: Dict[str, Any],
    classes: Iterable[str],
    class_sources: Dict[str, Dict[str, Any]],
    active: Dict[str, Any],
) -> Dict[str, Dict[str, int]]:
    raw_map = state.get("stats_by_class")
    normalized: Dict[str, Dict[str, int]] = {}
    if isinstance(raw_map, dict):
        for name, payload in raw_map.items():
            cls_name = _normalize_class_name(name)
            if not cls_name:
                continue
            normalized[cls_name] = _normalize_stats_block(payload)

    for cls_name in classes:
        candidates = _source_candidates_for_class(cls_name, class_sources, active, state)
        block: Any = None
        for src in candidates:
            if not isinstance(src, dict):
                continue
            block = src.get("stats")
            if block is not None:
                break
        fallback_block = _normalize_stats_block(block)

        if cls_name in normalized:
            current_block = _normalize_stats_block(normalized[cls_name])
            if current_block == _empty_stats() and block is not None:
                normalized[cls_name] = fallback_block
            else:
                normalized[cls_name] = current_block
            continue

        normalized[cls_name] = fallback_block

    state["stats_by_class"] = normalized
    return normalized


def _sanitize_equipped_iid(value: Any) -> Optional[str]:
    """Return a normalized armour instance id from assorted payload shapes."""

    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, Mapping):
        for key in ("iid", "instance_id", "wearing", "armour", "armor"):
            candidate = value.get(key)
            sanitized = _sanitize_equipped_iid(candidate)
            if sanitized:
                return sanitized
    return None


def _sanitize_ready_target(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        return token or None
    try:
        token = str(value).strip()
    except Exception:
        return None
    return token or None


def _sanitize_status_effect_entry(payload: Any) -> Optional[Dict[str, Any]]:
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        raw_id = payload.get("status_id") or payload.get("id")
        status_id = _string_key(raw_id)
        if not status_id:
            return None
        duration_raw = payload.get("duration")
        if duration_raw is None:
            duration_raw = payload.get("turns")
        duration = max(0, _sanitize_class_int(duration_raw, 0))
        entry: Dict[str, Any] = {"status_id": status_id, "duration": duration}
        return entry
    if isinstance(payload, str):
        status_id = payload.strip()
        if not status_id:
            return None
        return {"status_id": status_id, "duration": 0}
    return None


def _sanitize_status_effect_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        entries: List[Dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for item in payload:
            sanitized = _sanitize_status_effect_entry(item)
            if not sanitized:
                continue
            key = (sanitized["status_id"], sanitized["duration"])
            if key in seen:
                continue
            seen.add(key)
            entries.append(sanitized)
        return entries
    sanitized = _sanitize_status_effect_entry(payload)
    return [sanitized] if sanitized else []


def _ensure_status_effects_map(
    state: Dict[str, Any],
    classes: Iterable[str],
    class_sources: Dict[str, Dict[str, Any]],
    active: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    raw_map = state.get("status_effects_by_class")
    normalized: Dict[str, List[Dict[str, Any]]] = {}
    class_set = {cls for cls in classes if isinstance(cls, str) and cls}
    if isinstance(raw_map, Mapping):
        for name, payload in raw_map.items():
            cls_name = _normalize_class_name(name)
            if not cls_name or cls_name not in class_set:
                continue
            normalized[cls_name] = _sanitize_status_effect_list(payload)

    for cls_name in classes:
        if not isinstance(cls_name, str) or not cls_name:
            continue
        candidates = _source_candidates_for_class(cls_name, class_sources, active, state)
        fallback: Any = None
        for src in candidates:
            if not isinstance(src, Mapping):
                continue
            block = src.get("status_effects")
            if block is None:
                block = src.get("statuses")
            if block is not None:
                fallback = block
                break

        if cls_name in normalized:
            normalized[cls_name] = _sanitize_status_effect_list(normalized[cls_name])
            continue

        normalized[cls_name] = _sanitize_status_effect_list(fallback)

    state["status_effects_by_class"] = normalized
    return normalized


def _ensure_equipment_map(
    state: Dict[str, Any],
    classes: Iterable[str],
    class_sources: Dict[str, Dict[str, Any]],
    active: Dict[str, Any],
) -> Dict[str, Dict[str, Optional[str]]]:
    raw_map = state.get("equipment_by_class")
    normalized: Dict[str, Dict[str, Optional[str]]] = {}
    if isinstance(raw_map, Mapping):
        for name, payload in raw_map.items():
            cls_name = _normalize_class_name(name)
            if not cls_name:
                continue
            armour_value: Any
            if isinstance(payload, Mapping):
                armour_value = payload.get("armour")
            else:
                armour_value = payload
            normalized[cls_name] = {"armour": _sanitize_equipped_iid(armour_value)}

    for cls_name in classes:
        key = cls_name if isinstance(cls_name, str) and cls_name else None
        if not key:
            continue
        current_entry = normalized.get(key)
        current_value = (
            _sanitize_equipped_iid(current_entry.get("armour"))
            if isinstance(current_entry, Mapping)
            else None
        )
        if current_value:
            normalized[key] = {"armour": current_value}
            continue

        fallback: Optional[str] = None
        for source in _source_candidates_for_class(key, class_sources, active, state):
            if not isinstance(source, Mapping):
                continue
            eq_map = source.get("equipment_by_class")
            if isinstance(eq_map, Mapping):
                entry = eq_map.get(key)
                if isinstance(entry, Mapping):
                    fallback = _sanitize_equipped_iid(entry.get("armour"))
                else:
                    fallback = _sanitize_equipped_iid(entry)
                if fallback:
                    break
            direct = source.get("armour")
            if isinstance(direct, Mapping):
                fallback = _sanitize_equipped_iid(direct.get("wearing"))
            else:
                fallback = _sanitize_equipped_iid(direct)
            if fallback:
                break
            legacy_direct = source.get("armor")
            fallback = _sanitize_equipped_iid(legacy_direct)
            if fallback:
                break
        # Enforce invariant: equipped armour must be present in the class's bag.
        equipped = fallback
        try:
            bags_map = state.get("bags_by_class") or state.get("bags") or {}
            class_bag = list(bags_map.get(key) or [])
        except Exception:
            class_bag = []
        if equipped and equipped not in class_bag:
            equipped = None
        normalized[key] = {"armour": equipped}

    state["equipment_by_class"] = normalized
    return normalized


def _ensure_wielded_map(
    state: Dict[str, Any],
    classes: Iterable[str],
    class_sources: Dict[str, Dict[str, Any]],
    active: Dict[str, Any],
) -> Dict[str, Optional[str]]:
    raw_map = state.get("wielded_by_class")
    normalized: Dict[str, Optional[str]] = {}
    if isinstance(raw_map, Mapping):
        for name, payload in raw_map.items():
            cls_name = _normalize_class_name(name)
            if not cls_name:
                continue
            candidate: Optional[str]
            if isinstance(payload, Mapping):
                candidate = (
                    _sanitize_equipped_iid(payload.get("wielded"))
                    or _sanitize_equipped_iid(payload.get("weapon"))
                    or _sanitize_equipped_iid(payload.get("iid"))
                    or _sanitize_equipped_iid(payload.get("instance_id"))
                )
            else:
                candidate = _sanitize_equipped_iid(payload)
            normalized[cls_name] = candidate

    for cls_name in classes:
        key = cls_name if isinstance(cls_name, str) and cls_name else None
        if not key:
            continue
        current = normalized.get(key)
        candidate = _sanitize_equipped_iid(current)
        if not candidate:
            fallback: Optional[str] = None
            for source in _source_candidates_for_class(key, class_sources, active, state):
                if not isinstance(source, Mapping):
                    continue
                wmap = source.get("wielded_by_class")
                if isinstance(wmap, Mapping):
                    entry = wmap.get(key)
                    fallback = _sanitize_equipped_iid(entry)
                    if fallback:
                        break
                direct = source.get("wielded")
                if not fallback:
                    fallback = _sanitize_equipped_iid(direct)
                if not fallback:
                    fallback = _sanitize_equipped_iid(source.get("weapon"))
                if fallback:
                    break
            candidate = fallback
        try:
            bags_map = state.get("bags_by_class") or state.get("bags") or {}
            class_bag = [str(item) for item in bags_map.get(key) or [] if item]
        except Exception:
            class_bag = []
        if candidate and candidate not in class_bag:
            candidate = None
        normalized[key] = candidate

    state["wielded_by_class"] = normalized
    return normalized


def _ensure_ready_target_map(
    state: Dict[str, Any],
    classes: Iterable[str],
    class_sources: Dict[str, Dict[str, Any]],
    active: Dict[str, Any],
) -> Dict[str, Optional[str]]:
    raw_map = state.get("ready_target_by_class")
    normalized: Dict[str, Optional[str]] = {}
    if isinstance(raw_map, Mapping):
        for name, value in raw_map.items():
            cls_name = _normalize_class_name(name)
            if not cls_name:
                continue
            normalized[cls_name] = _sanitize_ready_target(value)

    target_map_raw = state.get("target_monster_id_by_class")
    if isinstance(target_map_raw, Mapping):
        for name, value in target_map_raw.items():
            cls_name = _normalize_class_name(name)
            if not cls_name:
                continue
            sanitized = _sanitize_ready_target(value)
            if cls_name not in normalized or normalized.get(cls_name) is None:
                normalized[cls_name] = sanitized

    for cls_name in classes:
        key = cls_name if isinstance(cls_name, str) and cls_name else None
        if not key:
            continue
        current = _sanitize_ready_target(normalized.get(key))
        if current:
            normalized[key] = current
            continue

        fallback: Optional[str] = None
        for source in _source_candidates_for_class(key, class_sources, active, state):
            if not isinstance(source, Mapping):
                continue
            ready_map = source.get("ready_target_by_class")
            if isinstance(ready_map, Mapping):
                fallback = _sanitize_ready_target(ready_map.get(key))
                if fallback:
                    break
            target_map = source.get("target_monster_id_by_class")
            if isinstance(target_map, Mapping):
                fallback = _sanitize_ready_target(target_map.get(key))
                if fallback:
                    break
            candidate = source.get("ready_target")
            if candidate is not None:
                fallback = _sanitize_ready_target(candidate)
                if fallback:
                    break
            candidate = source.get("target_monster_id")
            if candidate is not None:
                fallback = _sanitize_ready_target(candidate)
                if fallback:
                    break
        normalized[key] = fallback

    sanitized_map = {
        cls_name: _sanitize_ready_target(value) for cls_name, value in normalized.items()
    }
    state["ready_target_by_class"] = sanitized_map
    state["target_monster_id_by_class"] = dict(sanitized_map)
    return sanitized_map


def _log_wield_invariants(status: str, summary: str, healed: Iterable[str]) -> None:
    """Emit debug logs describing the outcome of wield invariant checks."""

    pdgb_active = _pdbg_enabled()
    edbg_active = _edbg_enabled()
    if not (pdgb_active or edbg_active):
        return

    healed_list = [entry for entry in healed if entry]
    healed_render = "|".join(healed_list)

    if pdgb_active:
        _pdbg_setup_file_logging()
        if healed_render:
            LOG_P.info("[playersdbg] %s wield :: %s healed=%s", status, summary, healed_render)
        else:
            LOG_P.info("[playersdbg] %s wield :: %s", status, summary)

    if edbg_active:
        payload: Dict[str, Any] = {"status": status, "summary": summary}
        if healed_render:
            payload["healed"] = healed_render
        _edbg_log("[ equip ] state=wield-invariants", **payload)


def _enforce_wield_invariants(
    state: Dict[str, Any],
    classes: Iterable[str],
    equipment_map: Mapping[str, Mapping[str, Optional[str]]],
    wield_map: Dict[str, Optional[str]],
    *,
    active_class: str,
) -> None:
    """Ensure wield invariants hold and emit debug logging if needed."""

    if not isinstance(wield_map, dict):
        return

    class_names: set[str] = set()
    for cls in classes:
        if isinstance(cls, str) and cls:
            class_names.add(cls)
    if isinstance(active_class, str) and active_class:
        class_names.add(active_class)
    for cls in list(wield_map.keys()):
        normalized = _normalize_class_name(cls)
        if normalized:
            class_names.add(normalized)

    bags_by_class = state.get("bags_by_class")
    bags_fallback = state.get("bags")
    bags_map: Mapping[str, Any] = bags_by_class if isinstance(bags_by_class, Mapping) else {}
    fallback_map: Mapping[str, Any] = bags_fallback if isinstance(bags_fallback, Mapping) else {}

    healed: List[str] = []
    summary_parts: List[str] = []

    for cls_name in sorted(class_names):
        bag_payload = bags_map.get(cls_name)
        if not isinstance(bag_payload, list):
            fallback_payload = fallback_map.get(cls_name)
            bag_payload = fallback_payload if isinstance(fallback_payload, list) else []
        bag_items = [str(item) for item in bag_payload if item is not None]

        equipment_entry = equipment_map.get(cls_name)
        armour_iid: Optional[str]
        if isinstance(equipment_entry, Mapping):
            armour_iid = _sanitize_equipped_iid(equipment_entry.get("armour"))
        else:
            armour_iid = _sanitize_equipped_iid(equipment_entry)

        original_weapon = _sanitize_equipped_iid(wield_map.get(cls_name))
        violation: Optional[str] = None
        if original_weapon and original_weapon not in bag_items:
            violation = "bag"
        elif original_weapon and armour_iid and armour_iid == original_weapon:
            violation = "armour"

        final_weapon: Optional[str]
        has_entry = cls_name in wield_map
        if violation:
            final_weapon = None
            healed.append(f"{cls_name}:{violation}:{original_weapon}")
        else:
            final_weapon = original_weapon

        if violation or has_entry:
            wield_map[cls_name] = final_weapon

        summary_parts.append(f"{cls_name}:{final_weapon or '-'}")

    summary = " ".join(summary_parts) if summary_parts else "<no-classes>"
    _log_wield_invariants("INV-OK", summary, healed)


def _set_armour_view(payload: Dict[str, Any], armour_iid: Optional[str]) -> None:
    if not isinstance(payload, dict):
        return
    existing = payload.get("armour")
    if isinstance(existing, Mapping):
        block = dict(existing)
    else:
        block = {}
    block["wearing"] = armour_iid
    payload["armour"] = block


def _set_wield_view(payload: Dict[str, Any], weapon_iid: Optional[str]) -> None:
    if not isinstance(payload, dict):
        return
    payload["wielded"] = weapon_iid


def _ensure_spells_map(state: Dict[str, Any], classes: Iterable[str]) -> Dict[str, Dict[str, List[str]]]:
    raw_map = state.get("spells_by_class")
    normalized: Dict[str, Dict[str, List[str]]] = {}
    if isinstance(raw_map, Mapping):
        for name, payload in raw_map.items():
            cls_name = _string_key(name)
            if not cls_name:
                continue
            normalized[cls_name] = _sanitize_spell_container(payload)

    for cls_name in classes:
        key = cls_name if isinstance(cls_name, str) and cls_name else None
        if not key:
            continue
        if key not in normalized:
            normalized[key] = {"known": [], "prepared": []}

    state["spells_by_class"] = normalized
    return normalized


def _ensure_spell_effects_map(
    state: Dict[str, Any], classes: Iterable[str]
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    raw_map = state.get("spell_effects_by_class")
    normalized: Dict[str, Dict[str, Dict[str, Any]]] = {}
    if isinstance(raw_map, Mapping):
        for name, payload in raw_map.items():
            cls_name = _string_key(name)
            if not cls_name:
                continue
            normalized[cls_name] = _sanitize_spell_effect_entry(payload)

    for cls_name in classes:
        key = cls_name if isinstance(cls_name, str) and cls_name else None
        if not key:
            continue
        entry = normalized.get(key)
        if entry is None:
            normalized[key] = {"personal": {}}
        else:
            personal = entry.get("personal")
            if not isinstance(personal, dict):
                entry["personal"] = {}

    state["spell_effects_by_class"] = normalized
    return normalized


def _apply_maps_to_profiles(
    state: Dict[str, Any],
    klass: str,
    active: Dict[str, Any],
    ions_map: Dict[str, int],
    rib_map: Dict[str, int],
    exhaustion_map: Dict[str, int],
    exp_map: Dict[str, int],
    level_map: Dict[str, int],
    hp_map: Dict[str, Dict[str, int]],
    stats_map: Dict[str, Dict[str, int]],
    equipment_map: Dict[str, Dict[str, Optional[str]]],
    wield_map: Dict[str, Optional[str]],
    ready_map: Dict[str, Optional[str]],
    status_map: Dict[str, List[Dict[str, Any]]],
) -> None:
    players = state.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, dict):
                continue
            cls_name = (
                _normalize_class_name(player.get("class"))
                or _normalize_class_name(player.get("name"))
            )
            if not cls_name:
                continue
            ion_val = ions_map.get(cls_name, 0)
            rib_val = rib_map.get(cls_name, 0)
            player["ions"] = ion_val
            player["Ions"] = ion_val
            player["riblets"] = rib_val
            player["Riblets"] = rib_val
            player["exhaustion"] = exhaustion_map.get(cls_name, 0)
            player["exp_points"] = exp_map.get(cls_name, 0)
            player["level"] = level_map.get(cls_name, 1)
            player["hp"] = dict(hp_map.get(cls_name, _empty_hp()))
            player["stats"] = dict(stats_map.get(cls_name, _empty_stats()))

            armour_entry = equipment_map.get(cls_name)
            armour_iid = None
            if isinstance(armour_entry, Mapping):
                armour_iid = _sanitize_equipped_iid(armour_entry.get("armour"))
            elif armour_entry is not None:
                armour_iid = _sanitize_equipped_iid(armour_entry)
            equipment = player.setdefault("equipment_by_class", {})
            if isinstance(equipment, dict):
                equipment[cls_name] = {"armour": armour_iid}
            _set_armour_view(player, armour_iid)

            weapon_iid = _sanitize_equipped_iid(wield_map.get(cls_name))
            wielded_map = player.setdefault("wielded_by_class", {})
            if isinstance(wielded_map, dict):
                wielded_map[cls_name] = weapon_iid
            _set_wield_view(player, weapon_iid)

            ready_target = _sanitize_ready_target(ready_map.get(cls_name))
            ready_map_entry = player.setdefault("ready_target_by_class", {})
            if isinstance(ready_map_entry, dict):
                ready_map_entry[cls_name] = ready_target
            target_map_entry = player.setdefault("target_monster_id_by_class", {})
            if isinstance(target_map_entry, dict):
                target_map_entry[cls_name] = ready_target
            player["ready_target"] = ready_target
            player["target_monster_id"] = ready_target

            status_entries = [dict(entry) for entry in status_map.get(cls_name, [])]
            status_map_entry = player.setdefault("status_effects_by_class", {})
            if isinstance(status_map_entry, dict):
                status_map_entry[cls_name] = status_entries
            player["status_effects"] = status_entries

    klass_name = klass if isinstance(klass, str) and klass else "Thief"
    active_hp = dict(hp_map.get(klass_name, _empty_hp()))
    active_stats = dict(stats_map.get(klass_name, _empty_stats()))
    active_ions = ions_map.get(klass_name, 0)
    active_riblets = rib_map.get(klass_name, 0)
    active_exhaustion = exhaustion_map.get(klass_name, 0)
    active_exp = exp_map.get(klass_name, 0)
    active_level = level_map.get(klass_name, 1)

    if isinstance(active, dict):
        active["ions"] = active_ions
        active["Ions"] = active_ions
        active["riblets"] = active_riblets
        active["Riblets"] = active_riblets
        active["exhaustion"] = active_exhaustion
        active["exp_points"] = active_exp
    active["level"] = active_level
    active["hp"] = active_hp
    active["stats"] = active_stats

    ready_target_active = _sanitize_ready_target(ready_map.get(klass_name))
    active_ready_map = active.setdefault("ready_target_by_class", {})
    if isinstance(active_ready_map, dict):
        active_ready_map[klass_name] = ready_target_active
    active_target_map = active.setdefault("target_monster_id_by_class", {})
    if isinstance(active_target_map, dict):
        active_target_map[klass_name] = ready_target_active
    active["ready_target"] = ready_target_active
    active["target_monster_id"] = ready_target_active

    active_status_entries = [dict(entry) for entry in status_map.get(klass_name, [])]
    active_status_map = active.setdefault("status_effects_by_class", {})
    if isinstance(active_status_map, dict):
        active_status_map[klass_name] = active_status_entries
    active["status_effects"] = active_status_entries

    active_armour_entry = equipment_map.get(klass_name)
    armour_iid = None
    if isinstance(active_armour_entry, Mapping):
        armour_iid = _sanitize_equipped_iid(active_armour_entry.get("armour"))
    elif active_armour_entry is not None:
        armour_iid = _sanitize_equipped_iid(active_armour_entry)
    active_equipment = active.setdefault("equipment_by_class", {})
    if isinstance(active_equipment, dict):
        active_equipment[klass_name] = {"armour": armour_iid}
    _set_armour_view(active, armour_iid)
    _set_armour_view(state, armour_iid)

    weapon_iid = _sanitize_equipped_iid(wield_map.get(klass_name))
    active_wield_map = active.setdefault("wielded_by_class", {})
    if isinstance(active_wield_map, dict):
        active_wield_map[klass_name] = weapon_iid
    _set_wield_view(active, weapon_iid)
    _set_wield_view(state, weapon_iid)

    state["ions"] = active_ions
    state["Ions"] = active_ions
    state["riblets"] = active_riblets
    state["Riblets"] = active_riblets
    state["exhaustion"] = active_exhaustion
    state["exp_points"] = active_exp
    state["level"] = active_level
    state["hp"] = dict(active_hp)
    state["stats"] = dict(active_stats)
    sanitized_ready_map = {
        cls_name: _sanitize_ready_target(value) for cls_name, value in ready_map.items()
    }
    state["ready_target_by_class"] = sanitized_ready_map
    state["target_monster_id_by_class"] = dict(sanitized_ready_map)
    state["status_effects_by_class"] = {
        cls_name: [dict(entry) for entry in status_map.get(cls_name, [])]
        for cls_name in status_map
    }


def _normalize_per_class_structures(
    state: Dict[str, Any], klass: str, active: Dict[str, Any], *, sparse_ions: bool = False
) -> Dict[str, Any]:
    if not isinstance(state, dict):
        return state

    if not isinstance(active, dict):
        active = {}

    classes, sources = _gather_class_sources(state, klass, active)
    klass_name = klass if isinstance(klass, str) and klass else "Thief"
    if klass_name not in classes:
        classes = list(classes) + [klass_name]

    ions_map = _ensure_int_map(
        state,
        "ions_by_class",
        _IONS_KEYS,
        0,
        classes,
        sources,
        active,
        fill_missing=not sparse_ions,
    )
    rib_map = _ensure_int_map(
        state,
        "riblets_by_class",
        _RIBLETS_KEYS,
        0,
        classes,
        sources,
        active,
    )
    exhaustion_map = _ensure_int_map(
        state,
        "exhaustion_by_class",
        ("exhaustion", "Exhaustion"),
        0,
        classes,
        sources,
        active,
    )
    exp_map = _ensure_int_map(
        state,
        "exp_by_class",
        _EXP_KEYS,
        0,
        classes,
        sources,
        active,
    )
    level_map = _ensure_int_map(
        state,
        "level_by_class",
        _LEVEL_KEYS,
        1,
        classes,
        sources,
        active,
    )
    hp_map = _ensure_hp_map(state, classes, sources, active)
    stats_map = _ensure_stats_map(state, classes, sources, active)

    equipment_map = _ensure_equipment_map(state, classes, sources, active)
    wield_map = _ensure_wielded_map(state, classes, sources, active)
    ready_map = _ensure_ready_target_map(state, classes, sources, active)
    status_map = _ensure_status_effects_map(state, classes, sources, active)

    _enforce_wield_invariants(
        state,
        classes,
        equipment_map,
        wield_map,
        active_class=klass_name,
    )

    _ensure_spells_map(state, classes)
    _ensure_spell_effects_map(state, classes)
    state["world_tile_effects"] = _sanitize_world_tile_effects(state.get("world_tile_effects"))

    _apply_maps_to_profiles(
        state,
        klass_name,
        active,
        ions_map,
        rib_map,
        exhaustion_map,
        exp_map,
        level_map,
        hp_map,
        stats_map,
        equipment_map,
        wield_map,
        ready_map,
        status_map,
    )

    return state


def _evaluate_invariants_with_details(state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    details: Dict[str, Any] = {"map_counts": {}}

    if not isinstance(state, dict):
        details["failure"] = "state-not-dict"
        return False, details

    players = state.get("players")
    if not isinstance(players, list):
        details["failure"] = "players-not-list"
        return False, details

    player_ids: set[str] = set()
    active_flags: List[str] = []
    for idx, player in enumerate(players):
        if not isinstance(player, dict):
            details["failure"] = f"player[{idx}]-not-dict"
            return False, details
        pid = player.get("id")
        if not isinstance(pid, str) or not pid:
            details["failure"] = f"player[{idx}]-missing-id"
            return False, details
        if pid in player_ids:
            details["failure"] = f"duplicate-player-id:{pid}"
            return False, details
        player_ids.add(pid)
        if player.get("is_active"):
            active_flags.append(pid)

    active_id = state.get("active_id")
    if active_flags:
        if len(active_flags) != 1:
            details["active_mismatch"] = f"is_active_count={len(active_flags)} active_id={active_id}"
        elif not isinstance(active_id, str) or active_id != active_flags[0]:
            details["active_mismatch"] = f"active_id={active_id} flag={active_flags[0]}"
    elif isinstance(active_id, str) and active_id:
        details["active_mismatch"] = f"active_id={active_id} without-flag"

    active = state.get("active")
    if not isinstance(active, dict):
        details["failure"] = "active-not-dict"
        return False, details

    klass = (
        _normalize_class_name(active.get("class"))
        or _normalize_class_name(state.get("class"))
        or _normalize_class_name(state.get("name"))
        or "Thief"
    )

    classes, _ = _gather_class_sources(state, klass, active)
    class_set = {cls_name for cls_name in classes if isinstance(cls_name, str) and cls_name}
    class_set.add(klass)

    ok = details.get("active_mismatch") is None

    sanitized_maps: Dict[str, Dict[str, Any]] = {}

    int_map_specs: Tuple[Tuple[str, int], ...] = (
        ("ions_by_class", 0),
        ("riblets_by_class", 0),
        ("exp_by_class", 0),
        ("level_by_class", 1),
    )

    for map_key, default in int_map_specs:
        payload = state.get(map_key)
        if isinstance(payload, dict):
            details["map_counts"][map_key] = len(payload)
        else:
            payload = {}
            details["map_counts"][map_key] = 0
            if details.get("missing_pair") is None:
                details["missing_pair"] = (map_key, "<missing-map>")
            ok = False

        sanitized_entries: Dict[str, int] = {}
        for cls_name in class_set:
            if cls_name not in payload:
                if details.get("missing_pair") is None:
                    details["missing_pair"] = (map_key, cls_name)
                ok = False
            raw_value = payload.get(cls_name)
            sanitized_entries[cls_name] = _sanitize_class_int(raw_value, default)
        sanitized_maps[map_key] = sanitized_entries

    hp_payload = state.get("hp_by_class")
    if isinstance(hp_payload, dict):
        details["map_counts"]["hp_by_class"] = len(hp_payload)
    else:
        hp_payload = {}
        details["map_counts"]["hp_by_class"] = 0
        if details.get("missing_pair") is None:
            details["missing_pair"] = ("hp_by_class", "<missing-map>")
        ok = False

    ready_payload = state.get("ready_target_by_class")
    if isinstance(ready_payload, dict):
        details["map_counts"]["ready_target_by_class"] = len(ready_payload)
        for cls_name in class_set:
            if cls_name not in ready_payload:
                if details.get("missing_pair") is None:
                    details["missing_pair"] = ("ready_target_by_class", cls_name)
                ok = False
    else:
        ready_payload = {}
        details["map_counts"]["ready_target_by_class"] = 0
        if details.get("missing_pair") is None:
            details["missing_pair"] = ("ready_target_by_class", "<missing-map>")
        ok = False

    target_payload = state.get("target_monster_id_by_class")
    if isinstance(target_payload, dict):
        details["map_counts"]["target_monster_id_by_class"] = len(target_payload)
        for cls_name in class_set:
            if cls_name not in target_payload:
                if details.get("missing_pair") is None:
                    details["missing_pair"] = ("target_monster_id_by_class", cls_name)
                ok = False
    else:
        target_payload = {}
        details["map_counts"]["target_monster_id_by_class"] = 0
        if details.get("missing_pair") is None:
            details["missing_pair"] = ("target_monster_id_by_class", "<missing-map>")
        ok = False

    if isinstance(ready_payload, dict) and isinstance(target_payload, dict):
        for cls_name in class_set:
            ready_val = _sanitize_ready_target(ready_payload.get(cls_name))
            target_val = _sanitize_ready_target(target_payload.get(cls_name))
            if ready_val != target_val:
                if details.get("target_mismatch") is None:
                    details["target_mismatch"] = (cls_name, ready_val, target_val)
                ok = False

    hp_map: Dict[str, Dict[str, int]] = {}
    hp_violation: Optional[Tuple[str, int, int]] = None
    for cls_name in class_set:
        if cls_name not in hp_payload:
            if details.get("missing_pair") is None:
                details["missing_pair"] = ("hp_by_class", cls_name)
            ok = False
        raw_entry = hp_payload.get(cls_name)
        normalized = _normalize_hp_block(raw_entry)
        hp_map[cls_name] = normalized
        if isinstance(raw_entry, dict):
            raw_cur = max(0, _coerce_int(raw_entry.get("current"), 0))
            raw_max_raw = raw_entry.get("max")
            if raw_max_raw is None:
                raw_max = raw_cur
            else:
                raw_max = max(0, _coerce_int(raw_max_raw, raw_cur))
        else:
            raw_cur = normalized["current"]
            raw_max = normalized["max"]
        if raw_cur > raw_max and hp_violation is None:
            hp_violation = (cls_name, raw_cur, raw_max)
    if hp_violation is not None:
        ok = False
        details["hp_violation"] = hp_violation
    sanitized_maps["hp_by_class"] = hp_map

    stats_payload = state.get("stats_by_class")
    if isinstance(stats_payload, dict):
        details["map_counts"]["stats_by_class"] = len(stats_payload)
    else:
        stats_payload = {}
        details["map_counts"]["stats_by_class"] = 0
        if details.get("missing_pair") is None:
            details["missing_pair"] = ("stats_by_class", "<missing-map>")
        ok = False

    stats_map: Dict[str, Dict[str, int]] = {}
    for cls_name in class_set:
        if cls_name not in stats_payload:
            if details.get("missing_pair") is None:
                details["missing_pair"] = ("stats_by_class", cls_name)
            ok = False
        stats_map[cls_name] = _normalize_stats_block(stats_payload.get(cls_name))
    sanitized_maps["stats_by_class"] = stats_map

    spells_payload = state.get("spells_by_class")
    if isinstance(spells_payload, dict):
        details["map_counts"]["spells_by_class"] = len(spells_payload)
    else:
        spells_payload = {}
        details["map_counts"]["spells_by_class"] = 0
        if details.get("failure") is None:
            details["failure"] = "spells_by_class-not-dict"
        ok = False

    def _valid_spell_list(values: Any) -> bool:
        if not isinstance(values, list):
            return False
        seen: set[str] = set()
        for item in values:
            if not isinstance(item, str) or not item or item in seen:
                return False
            seen.add(item)
        return True

    for cls_name in class_set:
        if cls_name not in spells_payload:
            if details.get("missing_pair") is None:
                details["missing_pair"] = ("spells_by_class", cls_name)
            ok = False
        entry = spells_payload.get(cls_name)
        if not isinstance(entry, Mapping):
            if details.get("failure") is None:
                details["failure"] = f"spells_by_class[{cls_name}]-not-dict"
            ok = False
            continue
        for key in ("known", "prepared"):
            values = entry.get(key)
            if not _valid_spell_list(values):
                if details.get("failure") is None:
                    details["failure"] = f"spells_by_class[{cls_name}].{key}-invalid"
                ok = False

    effects_payload = state.get("spell_effects_by_class")
    if isinstance(effects_payload, dict):
        details["map_counts"]["spell_effects_by_class"] = len(effects_payload)
    else:
        effects_payload = {}
        details["map_counts"]["spell_effects_by_class"] = 0
        if details.get("failure") is None:
            details["failure"] = "spell_effects_by_class-not-dict"
        ok = False

    for cls_name in class_set:
        if cls_name not in effects_payload:
            if details.get("missing_pair") is None:
                details["missing_pair"] = ("spell_effects_by_class", cls_name)
            ok = False
        entry = effects_payload.get(cls_name)
        if not isinstance(entry, Mapping):
            if details.get("failure") is None:
                details["failure"] = f"spell_effects_by_class[{cls_name}]-not-dict"
            ok = False
            continue
        personal = entry.get("personal")
        if not isinstance(personal, Mapping):
            if details.get("failure") is None:
                details["failure"] = f"spell_effects_by_class[{cls_name}].personal-not-dict"
            ok = False

    world_effects = state.get("world_tile_effects")
    if isinstance(world_effects, Mapping):
        details["map_counts"]["world_tile_effects"] = len(world_effects)
    else:
        details["map_counts"]["world_tile_effects"] = 0
        if details.get("failure") is None:
            details["failure"] = "world_tile_effects-not-dict"
        ok = False

    ions_expected = sanitized_maps.get("ions_by_class", {}).get(klass, 0)
    riblets_expected = sanitized_maps.get("riblets_by_class", {}).get(klass, 0)

    mirror_mismatch: Optional[str] = None

    def _assert_mirror(scope: str, key: str, actual: Any, expected: int) -> None:
        nonlocal ok, mirror_mismatch
        value = _coerce_int(actual, 0)
        if value != expected and mirror_mismatch is None:
            mirror_mismatch = f"{scope}.{key}={value} expected={expected}"
        if value != expected:
            ok = False

    _assert_mirror("state", "ions", state.get("ions"), ions_expected)
    _assert_mirror("state", "Ions", state.get("Ions"), ions_expected)
    _assert_mirror("state", "riblets", state.get("riblets"), riblets_expected)
    _assert_mirror("state", "Riblets", state.get("Riblets"), riblets_expected)

    _assert_mirror("active", "ions", active.get("ions"), ions_expected)
    _assert_mirror("active", "Ions", active.get("Ions"), ions_expected)
    _assert_mirror("active", "riblets", active.get("riblets"), riblets_expected)
    _assert_mirror("active", "Riblets", active.get("Riblets"), riblets_expected)

    if mirror_mismatch is not None:
        details["mirror_mismatch"] = mirror_mismatch

    items_ok, items_summary = _evaluate_item_instance_invariants()
    details["items_instances"] = items_summary
    if not items_ok and details.get("failure") is None:
        details["failure"] = "items-instances"
    ok = ok and items_ok

    return ok and details.get("failure") is None, details


def _evaluate_invariants(state: Dict[str, Any]) -> bool:
    ok, _ = _evaluate_invariants_with_details(state)
    return ok


def _normalize_player_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``state`` in canonical form for single-player data structures."""

    if not isinstance(state, dict):
        return {"players": [], "active_id": None}
    if not _has_profile_payload(state):
        return state

    ensure_active_profile(state, ctx={})

    active = state.get("active")
    if not isinstance(active, dict):
        active = {}
        state["active"] = active

    klass_raw = active.get("class") or state.get("class") or state.get("name")
    klass = str(klass_raw) if isinstance(klass_raw, str) and klass_raw else "Thief"
    active["class"] = klass
    if "class" not in state or not state.get("class"):
        state["class"] = klass

    raw_inventory: Optional[List[Any]]
    inv_top = state.get("inventory")
    if isinstance(inv_top, list):
        raw_inventory = inv_top
    else:
        active_inv = active.get("inventory") if isinstance(active, dict) else None
        raw_inventory = active_inv if isinstance(active_inv, list) else None

    cleaned_inventory = []
    if isinstance(raw_inventory, list):
        cleaned_inventory = [item for item in raw_inventory if item is not None]

    bag_from_top = [item for item in cleaned_inventory if item is not None]
    bags = state.get("bags")
    if not isinstance(bags, dict):
        bags = {}
        state["bags"] = bags
        bag = bag_from_top
    else:
        existing_bag = bags.get(klass)
        if bag_from_top:
            normalized_existing = [
                [item for item in (bags.get(name) or []) if item is not None]
                for name in bags
                if name != klass and isinstance(bags.get(name), list)
            ]
            if bag_from_top in normalized_existing:
                bag = [item for item in existing_bag if item is not None] if isinstance(existing_bag, list) else []
            else:
                bag = bag_from_top
        elif isinstance(existing_bag, list):
            bag = [item for item in existing_bag if item is not None]
        else:
            bag = []

    bags[klass] = bag
    state["inventory"] = bags[klass]
    active["inventory"] = bags[klass]

    sparse_ions = bool(state.get("_sparse_ions_by_class"))

    _normalize_per_class_structures(state, klass, active, sparse_ions=sparse_ions)

    return state


def migrate_per_class_fields(state: Dict[str, Any]) -> Dict[str, Any]:
    """Populate per-class structures from legacy scalar fields when needed."""

    if not isinstance(state, dict):
        return state

    legacy_snapshot = copy.deepcopy(state)
    legacy_values = _collect_legacy_snapshots(legacy_snapshot)

    normalized = _normalize_player_state(state)

    active = normalized.get("active")
    if not isinstance(active, dict):
        active = {}
        normalized["active"] = active

    klass = get_active_class(normalized)

    sparse_ions = bool(normalized.pop("_sparse_ions_by_class", False))

    ions_map = normalized.setdefault("ions_by_class", {})
    rib_map = normalized.setdefault("riblets_by_class", {})
    exp_map = normalized.setdefault("exp_by_class", {})
    level_map = normalized.setdefault("level_by_class", {})
    hp_map = normalized.setdefault("hp_by_class", {})
    stats_map = normalized.setdefault("stats_by_class", {})
    ready_map = normalized.setdefault("ready_target_by_class", {})
    target_map = normalized.setdefault("target_monster_id_by_class", {})

    for cls_name, payload in legacy_values.items():
        if not isinstance(cls_name, str) or not cls_name:
            continue

        ions_value = payload.get("ions")
        if ions_value is not None:
            if sparse_ions and cls_name != klass:
                pass
            else:
                if cls_name not in ions_map or _sanitize_class_int(ions_map.get(cls_name), 0) == 0:
                    ions_map[cls_name] = _sanitize_class_int(ions_value, 0)

        rib_value = payload.get("riblets")
        if rib_value is not None:
            if cls_name not in rib_map or _sanitize_class_int(rib_map.get(cls_name), 0) == 0:
                rib_map[cls_name] = _sanitize_class_int(rib_value, 0)

        exp_value = payload.get("exp")
        if exp_value is not None:
            if cls_name not in exp_map or _sanitize_class_int(exp_map.get(cls_name), 0) == 0:
                exp_map[cls_name] = _sanitize_class_int(exp_value, 0)

        level_value = payload.get("level")
        if level_value is not None:
            if cls_name not in level_map or _sanitize_class_int(level_map.get(cls_name), 1) == 1:
                level_map[cls_name] = _sanitize_class_int(level_value, 1)

        hp_value = payload.get("hp")
        if hp_value is not None:
            existing_hp = hp_map.get(cls_name)
            if not isinstance(existing_hp, Mapping) or _normalize_hp_block(existing_hp) == _empty_hp():
                hp_map[cls_name] = _normalize_hp_block(hp_value)

        stats_value = payload.get("stats")
        if stats_value is not None:
            existing_stats = stats_map.get(cls_name)
            if not isinstance(existing_stats, Mapping) or _normalize_stats_block(existing_stats) == _empty_stats():
                stats_map[cls_name] = _normalize_stats_block(stats_value)

        wield_value = payload.get("wielded")
        if wield_value is not None:
            wield_map = normalized.setdefault("wielded_by_class", {})
            current_wield = _sanitize_equipped_iid(wield_map.get(cls_name))
            sanitized_wield = _sanitize_equipped_iid(wield_value)
            if sanitized_wield and not current_wield:
                wield_map[cls_name] = sanitized_wield

        target_value = payload.get("ready_target")
        sanitized_ready = _sanitize_ready_target(target_value)
        if sanitized_ready is None:
            target_map_payload = payload.get("target_monster_id_by_class")
            if isinstance(target_map_payload, Mapping):
                sanitized_ready = _sanitize_ready_target(target_map_payload.get(cls_name))
        if sanitized_ready is None and "target_monster_id" in payload:
            sanitized_ready = _sanitize_ready_target(payload.get("target_monster_id"))
        if sanitized_ready is not None:
            current_ready = _sanitize_ready_target(ready_map.get(cls_name))
            current_target = _sanitize_ready_target(target_map.get(cls_name))
            if not current_ready:
                ready_map[cls_name] = sanitized_ready
            if not current_target:
                target_map[cls_name] = sanitized_ready

    _normalize_per_class_structures(normalized, klass, active, sparse_ions=sparse_ions)

    return normalized


def load_state() -> Dict[str, Any]:
    path = _player_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            state: Dict[str, Any] = json.load(f)
        before = json.dumps(state, sort_keys=True, ensure_ascii=False)
        migrated = migrate_per_class_fields(state)
        after = json.dumps(migrated, sort_keys=True, ensure_ascii=False)
        if after != before:
            _persist_canonical(migrated)
        state = migrated
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"players": [], "active_id": None}
    _playersdbg_log("LOAD", state)
    _check_invariants_and_log(state, "after load")
    return state


def save_state(state: Dict[str, Any]) -> None:
    # Safety net: never write a state without an ``active`` profile present.
    to_save: Dict[str, Any]
    if isinstance(state, dict):
        to_save = copy.deepcopy(state)
    else:
        to_save = {}
    active = to_save.get("active")
    if not isinstance(active, dict):
        try:
            prev = load_state()
            prev_active = prev.get("active") if isinstance(prev, dict) else None
            if isinstance(prev_active, dict):
                to_save["active"] = copy.deepcopy(prev_active)
        except Exception:
            # If we cannot backfill from disk, synthesize a minimal default.
            to_save["active"] = {
                "class": to_save.get("class") or to_save.get("name") or "Thief",
                "pos": [2000, 0, 0],
            }
    normalized = migrate_per_class_fields(to_save)
    _persist_canonical(normalized)
    _playersdbg_log("SAVE", normalized)
    _check_invariants_and_log(normalized, "after save")


def on_class_switch(
    prev_class: Optional[str], next_class: Optional[str], state: Dict[str, Any]
) -> Dict[str, Any]:
    normalized_state = _normalize_player_state(state if isinstance(state, dict) else {})
    prev = _normalize_class_name(prev_class)
    nxt = _normalize_class_name(next_class)
    if prev and prev != nxt:
        effects_map = normalized_state.setdefault("spell_effects_by_class", {})
        entry = effects_map.get(prev)
        if isinstance(entry, Mapping):
            sanitized_entry = _sanitize_spell_effect_entry(entry)
        else:
            sanitized_entry = {"personal": {}}
        sanitized_entry["personal"] = {}
        effects_map[prev] = sanitized_entry
    return normalized_state


def get_active_class(state: Dict[str, Any]) -> str:
    """Return the active class, preferring multi-profile resolution."""

    if not isinstance(state, dict):
        return "Thief"

    players = state.get("players")
    active_id = state.get("active_id")
    if isinstance(players, list) and active_id:
        for player in players:
            if not isinstance(player, Mapping):
                continue
            if player.get("id") != active_id:
                continue
            candidate = player.get("class") or player.get("name")
            if isinstance(candidate, str) and candidate:
                return candidate
            break

    active = state.get("active")
    if isinstance(active, Mapping):
        klass = active.get("class") or active.get("name")
        if isinstance(klass, str) and klass:
            return klass

    fallback = state.get("class") or state.get("name")
    return fallback if isinstance(fallback, str) and fallback else "Thief"


def _prepare_active_storage(
    state: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Return ``(normalized_state, active_profile, class_name)`` for helpers."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)

    active = normalized.get("active")
    if not isinstance(active, dict):
        active = {}
        normalized["active"] = active

    if not isinstance(active.get("class"), str) or not active.get("class"):
        active["class"] = cls

    if not isinstance(normalized.get("class"), str) or not normalized.get("class"):
        normalized["class"] = cls

    return normalized, active, cls


def get_ions_for_active(state: Dict[str, Any]) -> int:
    """Return the ion balance for the active class in ``state``."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    ion_map = normalized.get("ions_by_class", {})
    if isinstance(ion_map, dict):
        value = ion_map.get(cls)
        if value is not None:
            return _coerce_int(value, 0)
    # Fallback to legacy scalar locations when class-scoped entries are missing.
    legacy_candidates: List[Any] = [
        normalized.get("ions"),
        normalized.get("Ions"),
    ]
    active = normalized.get("active")
    if isinstance(active, Mapping):
        legacy_candidates.extend([active.get("ions"), active.get("Ions")])
    players = normalized.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            player_class = _normalize_class_name(player.get("class"))
            if player_class == cls or (
                player.get("id") == normalized.get("active_id") and player_class is None
            ):
                legacy_candidates.extend([player.get("ions"), player.get("Ions")])
                break
    for candidate in legacy_candidates:
        if candidate is not None:
            return _coerce_int(candidate, 0)
    return 0


def set_ions_for_active(state: Dict[str, Any], amount: int) -> int:
    """Set ions for the active class to ``amount`` and persist."""

    normalized, active, cls = _prepare_active_storage(state)
    ion_map = normalized.setdefault("ions_by_class", {})
    new_total = max(0, _coerce_int(amount, 0))
    ion_map[cls] = new_total

    normalized["ions"] = new_total
    normalized["Ions"] = new_total
    active["ions"] = new_total
    active["Ions"] = new_total
    active["ions_by_class"] = dict(ion_map)
    players = normalized.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            player_class = _normalize_class_name(player.get("class")) or _normalize_class_name(
                player.get("name")
            )
            player_id = player.get("id")
            if player_class == cls or player_id == normalized.get("active_id"):
                player["ions"] = new_total
                player["Ions"] = new_total
                player["ions_by_class"] = dict(ion_map)
                break

    save_state(normalized)
    return new_total


def spend_ions_for_active(state: Dict[str, Any], amount: int) -> Tuple[bool, int]:
    """Attempt to spend ``amount`` ions for the active class."""

    required = max(0, _coerce_int(amount, 0))
    current = get_ions_for_active(state)
    if required <= 0:
        return True, current
    if current < required:
        return False, current
    remaining = set_ions_for_active(state, current - required)
    return True, remaining


def get_riblets_for_active(state: Dict[str, Any]) -> int:
    """Return the riblet balance for the active class in ``state``."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    rib_map = normalized.get("riblets_by_class", {})
    if isinstance(rib_map, dict):
        value = rib_map.get(cls)
        if value is not None:
            return _coerce_int(value, 0)
    return 0


def set_riblets_for_active(state: Dict[str, Any], amount: int) -> int:
    """Set riblets for the active class to ``amount`` and persist."""

    normalized, active, cls = _prepare_active_storage(state)
    rib_map = normalized.setdefault("riblets_by_class", {})
    new_total = max(0, _coerce_int(amount, 0))
    rib_map[cls] = new_total

    normalized["riblets"] = new_total
    normalized["Riblets"] = new_total
    active["riblets"] = new_total
    active["Riblets"] = new_total
    players = normalized.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            player_class = _normalize_class_name(player.get("class")) or _normalize_class_name(
                player.get("name")
            )
            player_id = player.get("id")
            if player_class == cls or player_id == normalized.get("active_id"):
                player["riblets"] = new_total
                player["Riblets"] = new_total
                break

    save_state(normalized)
    return new_total


def get_equipped_armour_id(state: Dict[str, Any]) -> Optional[str]:
    """Return the instance id of the equipped armour for the active class."""

    if not isinstance(state, Mapping):
        return None

    cls = get_active_class(state)

    def _from_payload(payload: Any) -> Optional[str]:
        if not isinstance(payload, Mapping):
            return None
        equipment = payload.get("equipment_by_class")
        if isinstance(equipment, Mapping):
            entry = equipment.get(cls)
            if isinstance(entry, Mapping):
                candidate = _sanitize_equipped_iid(entry.get("armour"))
                if candidate:
                    return candidate
            elif entry is not None:
                candidate = _sanitize_equipped_iid(entry)
                if candidate:
                    return candidate
        direct = payload.get("armour")
        if isinstance(direct, Mapping):
            candidate = _sanitize_equipped_iid(direct.get("wearing"))
            if candidate:
                return candidate
        candidate = _sanitize_equipped_iid(direct)
        if candidate:
            return candidate
        legacy = payload.get("armor")
        return _sanitize_equipped_iid(legacy)

    candidates: List[Mapping[str, Any]] = []
    candidates.append(state)
    active = state.get("active")
    if isinstance(active, Mapping):
        candidates.append(active)
    players = state.get("players")
    active_id = state.get("active_id")
    if isinstance(players, list):
        for idx, player in enumerate(players):
            if not isinstance(player, Mapping):
                continue
            if active_id:
                if player.get("id") != active_id:
                    continue
                candidates.append(player)
                break
            if idx == 0:
                candidates.append(player)
                break

    for payload in candidates:
        armour_iid = _from_payload(payload)
        if armour_iid:
            return armour_iid

    return _from_payload(state)


def get_wielded_weapon_id(state: Dict[str, Any]) -> Optional[str]:
    """Return the wielded weapon instance id for the active class."""

    if not isinstance(state, Mapping):
        return None

    cls = get_active_class(state)

    def _from_payload(payload: Any) -> Optional[str]:
        if not isinstance(payload, Mapping):
            return None
        wield_map = payload.get("wielded_by_class")
        if isinstance(wield_map, Mapping):
            entry = wield_map.get(cls)
            if isinstance(entry, Mapping):
                candidate = (
                    _sanitize_equipped_iid(entry.get("wielded"))
                    or _sanitize_equipped_iid(entry.get("weapon"))
                    or _sanitize_equipped_iid(entry.get("iid"))
                    or _sanitize_equipped_iid(entry.get("instance_id"))
                )
                if candidate:
                    return candidate
            else:
                candidate = _sanitize_equipped_iid(entry)
                if candidate:
                    return candidate
        candidate = _sanitize_equipped_iid(payload.get("wielded"))
        if candidate:
            return candidate
        candidate = _sanitize_equipped_iid(payload.get("weapon"))
        if candidate:
            return candidate
        return None

    candidates: List[Mapping[str, Any]] = []
    candidates.append(state)
    active = state.get("active")
    if isinstance(active, Mapping):
        candidates.append(active)
    players = state.get("players")
    active_id = state.get("active_id")
    if isinstance(players, list):
        for idx, player in enumerate(players):
            if not isinstance(player, Mapping):
                continue
            if active_id:
                if player.get("id") != active_id:
                    continue
                candidates.append(player)
                break
            if idx == 0:
                candidates.append(player)
                break

    for payload in candidates:
        weapon_iid = _from_payload(payload)
        if weapon_iid:
            return weapon_iid

    return _from_payload(state)


def equip_armour(iid: str) -> str:
    """Equip the given armour instance for the active class."""

    sanitized = _sanitize_equipped_iid(iid)
    if not sanitized:
        raise ValueError("armour iid must be a non-empty string")

    state = load_state()
    normalized, active, cls = _prepare_active_storage(state)

    bags = normalized.setdefault("bags", {})
    existing_bag = bags.get(cls)
    bag_list = [str(item) for item in existing_bag or [] if item]
    if sanitized not in bag_list:
        raise ValueError("armour iid is not present in the active inventory")

    equipment_map = normalized.setdefault("equipment_by_class", {})
    entry = equipment_map.setdefault(cls, {"armour": None})
    current = _sanitize_equipped_iid(entry.get("armour"))
    if current and current != sanitized:
        raise ValueError("armour slot already occupied")

    entry["armour"] = sanitized
    bag_list = [item for item in bag_list if item != sanitized]
    bags[cls] = list(bag_list)
    normalized["inventory"] = list(bag_list)
    active["inventory"] = list(bag_list)

    active_equipment = active.setdefault("equipment_by_class", {})
    if isinstance(active_equipment, dict):
        active_equipment[cls] = {"armour": sanitized}
    _set_armour_view(active, sanitized)
    _set_armour_view(normalized, sanitized)

    players = normalized.get("players")
    active_id = normalized.get("active_id")
    if isinstance(players, list):
        for idx, player in enumerate(players):
            if not isinstance(player, Mapping):
                continue
            is_active = False
            if active_id:
                is_active = player.get("id") == active_id
            else:
                is_active = idx == 0
            if not is_active:
                continue
            player.setdefault("bags", {})[cls] = list(bag_list)
            player["inventory"] = list(bag_list)
            slot_map = player.setdefault("equipment_by_class", {})
            if isinstance(slot_map, dict):
                slot_map[cls] = {"armour": sanitized}
            _set_armour_view(player, sanitized)
            break

    save_state(normalized)
    return sanitized


def unequip_armour() -> Optional[str]:
    """Remove and return the equipped armour instance for the active class."""

    state = load_state()
    normalized, active, cls = _prepare_active_storage(state)

    equipment_map = normalized.setdefault("equipment_by_class", {})
    entry = equipment_map.setdefault(cls, {"armour": None})
    current = _sanitize_equipped_iid(entry.get("armour"))
    if not current:
        return None

    bags = normalized.setdefault("bags", {})
    existing_bag = bags.get(cls)
    bag_list = [str(item) for item in existing_bag or [] if item]
    if current in bag_list:
        raise ValueError("armour instance already present in inventory")

    bag_list.append(current)
    bags[cls] = list(bag_list)
    normalized["inventory"] = list(bag_list)
    active["inventory"] = list(bag_list)

    entry["armour"] = None
    active_equipment = active.setdefault("equipment_by_class", {})
    if isinstance(active_equipment, dict):
        active_equipment[cls] = {"armour": None}
    _set_armour_view(active, None)
    _set_armour_view(normalized, None)

    players = normalized.get("players")
    active_id = normalized.get("active_id")
    if isinstance(players, list):
        for idx, player in enumerate(players):
            if not isinstance(player, Mapping):
                continue
            is_active = False
            if active_id:
                is_active = player.get("id") == active_id
            else:
                is_active = idx == 0
            if not is_active:
                continue
            player.setdefault("bags", {})[cls] = list(bag_list)
            player["inventory"] = list(bag_list)
            slot_map = player.setdefault("equipment_by_class", {})
            if isinstance(slot_map, dict):
                slot_map[cls] = {"armour": None}
            _set_armour_view(player, None)
            break

    save_state(normalized)
    return current


def set_wielded_weapon(iid: Optional[str]) -> Optional[str]:
    """Set the wielded weapon for the active class to ``iid`` and persist."""

    sanitized = _sanitize_equipped_iid(iid)
    state = load_state()
    normalized, active, cls = _prepare_active_storage(state)

    bags = normalized.setdefault("bags", {})
    bag_list = [str(item) for item in bags.get(cls) or [] if item]
    if sanitized and sanitized not in bag_list:
        raise ValueError("weapon iid is not present in the active inventory")

    wield_map = normalized.setdefault("wielded_by_class", {})
    if isinstance(wield_map, dict):
        wield_map[cls] = sanitized
    normalized["wielded_by_class"] = dict(wield_map)
    _set_wield_view(normalized, sanitized)

    active_wield = active.setdefault("wielded_by_class", {})
    if isinstance(active_wield, dict):
        active_wield[cls] = sanitized
    _set_wield_view(active, sanitized)

    players = normalized.get("players")
    active_id = normalized.get("active_id")
    if isinstance(players, list):
        for idx, player in enumerate(players):
            if not isinstance(player, Mapping):
                continue
            is_active = False
            if active_id:
                is_active = player.get("id") == active_id
            else:
                is_active = idx == 0
            if not is_active:
                continue
            bags_map = player.setdefault("bags", {})
            if isinstance(bags_map, dict):
                bags_map.setdefault(cls, list(bag_list))
            player_wield_map = player.setdefault("wielded_by_class", {})
            if isinstance(player_wield_map, dict):
                player_wield_map[cls] = sanitized
            _set_wield_view(player, sanitized)
            break

    save_state(normalized)
    return sanitized


def get_exhaustion_for_active(state: Dict[str, Any]) -> int:
    """Return the exhaustion value for the active class in ``state``."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    payload = normalized.get("exhaustion_by_class", {})
    if isinstance(payload, dict):
        value = payload.get(cls)
        if value is not None:
            return _coerce_int(value, 0)
    return 0


def set_exhaustion_for_active(state: Dict[str, Any], amount: int) -> int:
    """Set exhaustion for the active class to ``amount`` and persist."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    payload = normalized.setdefault("exhaustion_by_class", {})
    new_value = max(0, _coerce_int(amount, 0))
    payload[cls] = new_value

    active = normalized.get("active")
    if not isinstance(active, dict):
        active = {}

    _normalize_per_class_structures(normalized, cls, active)
    players = normalized.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            player_class = _normalize_class_name(player.get("class")) or _normalize_class_name(
                player.get("name")
            )
            player_id = player.get("id")
            if player_class == cls or player_id == normalized.get("active_id"):
                player["exhaustion"] = new_value
                break

    save_state(normalized)
    return new_value


def get_exp_for_active(state: Dict[str, Any]) -> int:
    """Return the experience points for the active class in ``state``."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    payload = normalized.get("exp_by_class", {})
    if isinstance(payload, dict):
        value = payload.get(cls)
        if value is not None:
            return _coerce_int(value, 0)
    return 0


def set_exp_for_active(state: Dict[str, Any], amount: int) -> int:
    """Set experience points for the active class to ``amount`` and persist."""

    normalized, active, cls = _prepare_active_storage(state)
    payload = normalized.setdefault("exp_by_class", {})
    new_value = max(0, _coerce_int(amount, 0))
    payload[cls] = new_value

    normalized["exp_points"] = new_value
    active["exp_points"] = new_value
    players = normalized.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            player_class = _normalize_class_name(player.get("class")) or _normalize_class_name(
                player.get("name")
            )
            player_id = player.get("id")
            if player_class == cls or player_id == normalized.get("active_id"):
                player["exp_points"] = new_value
                break

    save_state(normalized)
    return new_value


def get_level_for_active(state: Dict[str, Any]) -> int:
    """Return the level for the active class in ``state``."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    payload = normalized.get("level_by_class", {})
    if isinstance(payload, dict):
        value = payload.get(cls)
        if value is not None:
            return max(1, _coerce_int(value, 1))
    return 1


def set_level_for_active(state: Dict[str, Any], amount: int) -> int:
    """Set the level for the active class to ``amount`` and persist."""

    normalized, active, cls = _prepare_active_storage(state)
    payload = normalized.setdefault("level_by_class", {})
    new_value = max(1, _coerce_int(amount, 1))
    payload[cls] = new_value

    normalized["level"] = new_value
    active["level"] = new_value
    players = normalized.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            player_class = _normalize_class_name(player.get("class")) or _normalize_class_name(
                player.get("name")
            )
            player_id = player.get("id")
            if player_class == cls or player_id == normalized.get("active_id"):
                player["level"] = new_value
                break

    save_state(normalized)
    return new_value


def get_hp_for_active(state: Dict[str, Any]) -> Dict[str, int]:
    """Return the HP block for the active class in ``state``."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    payload = normalized.get("hp_by_class", {})
    if isinstance(payload, dict):
        entry = payload.get(cls)
        if isinstance(entry, dict):
            return dict(_normalize_hp_block(entry))
    return _empty_hp()


def set_hp_for_active(
    state: Dict[str, Any], hp: Mapping[str, Any], /, *legacy: Any
) -> Dict[str, int]:
    """Set HP for the active class and persist the result."""

    if legacy:
        current = _coerce_int(hp, 0)
        max_raw = legacy[0] if legacy else current
        maximum = _coerce_int(max_raw, current)
        payload: Mapping[str, Any] = {"current": current, "max": maximum}
    else:
        payload = hp

    normalized, active, cls = _prepare_active_storage(state)
    block = _normalize_hp_block(payload)

    hp_map = normalized.setdefault("hp_by_class", {})
    sanitized = dict(block)
    hp_map[cls] = sanitized

    normalized["hp"] = dict(sanitized)
    active["hp"] = dict(sanitized)

    players = normalized.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            player_class = _normalize_class_name(player.get("class")) or _normalize_class_name(
                player.get("name")
            )
            player_id = player.get("id")
            if player_class == cls or player_id == normalized.get("active_id"):
                player["hp"] = dict(sanitized)
                break

    save_state(normalized)
    return dict(sanitized)


def heal_active(state: Dict[str, Any], amount: int) -> Tuple[int, Dict[str, int]]:
    """Increase the active class HP by up to ``amount`` points."""

    heal_amount = max(0, _coerce_int(amount, 0))
    if heal_amount <= 0:
        return 0, get_hp_for_active(state)

    hp_block = get_hp_for_active(state)
    current = _coerce_int(hp_block.get("current"), 0)
    maximum = max(current, _coerce_int(hp_block.get("max"), current))
    missing = max(0, maximum - current)
    if missing <= 0:
        return 0, hp_block

    applied = min(heal_amount, missing)
    updated = set_hp_for_active(state, {"current": current + applied, "max": maximum})
    return applied, updated


def get_stats_for_active(state: Dict[str, Any]) -> Dict[str, int]:
    """Return the ability scores for the active class in ``state``."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    payload = normalized.get("stats_by_class", {})
    if isinstance(payload, dict):
        entry = payload.get(cls)
        if isinstance(entry, Mapping):
            return dict(_normalize_stats_block(entry))
    return _empty_stats()


def set_stats_for_active(
    state: Dict[str, Any], stats: Mapping[str, Any]
) -> Dict[str, int]:
    """Set ability scores for the active class and persist."""

    normalized, active, cls = _prepare_active_storage(state)
    payload = normalized.setdefault("stats_by_class", {})
    sanitized = _normalize_stats_block(stats)
    payload[cls] = dict(sanitized)

    normalized["stats"] = dict(sanitized)
    active["stats"] = dict(sanitized)

    players = normalized.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            player_class = _normalize_class_name(player.get("class")) or _normalize_class_name(
                player.get("name")
            )
            player_id = player.get("id")
            if player_class == cls or player_id == normalized.get("active_id"):
                player["stats"] = dict(sanitized)
                break

    save_state(normalized)
    return dict(sanitized)


def get_ready_target_map(state: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Return a mapping of class name to sanitized ready-target ids."""

    normalized = _normalize_player_state(state)
    ready_payload = normalized.get("ready_target_by_class")
    target_payload = normalized.get("target_monster_id_by_class")
    if not isinstance(ready_payload, Mapping) and not isinstance(target_payload, Mapping):
        return {}

    result: Dict[str, Optional[str]] = {}
    if isinstance(ready_payload, Mapping):
        for name, value in ready_payload.items():
            cls_name = _normalize_class_name(name)
            if not cls_name:
                continue
            result[cls_name] = _sanitize_ready_target(value)
    if isinstance(target_payload, Mapping):
        for name, value in target_payload.items():
            cls_name = _normalize_class_name(name)
            if not cls_name:
                continue
            sanitized = _sanitize_ready_target(value)
            if cls_name not in result or result[cls_name] is None:
                result[cls_name] = sanitized
    return result


def get_ready_target_for_active(state: Dict[str, Any]) -> Optional[str]:
    """Return the ready target id for the active class when present."""

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    ready_payload = normalized.get("ready_target_by_class")
    target_payload = normalized.get("target_monster_id_by_class")
    if isinstance(ready_payload, Mapping):
        candidate = ready_payload.get(cls)
        sanitized = _sanitize_ready_target(candidate)
        if sanitized:
            return sanitized
    if isinstance(target_payload, Mapping):
        candidate = target_payload.get(cls)
        sanitized = _sanitize_ready_target(candidate)
        if sanitized:
            return sanitized
    active = normalized.get("active")
    if isinstance(active, Mapping):
        candidate = active.get("ready_target") or active.get("target_monster_id")
        sanitized = _sanitize_ready_target(candidate)
        if sanitized:
            return sanitized
    return None


def _update_ready_target_for_active(
    monster_id: Optional[str], *, reason: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    ctx = _current_runtime_ctx()
    runtime_mode = False
    state: Mapping[str, Any]

    if ctx is not None:
        state_hint = ctx.get("player_state")
        if isinstance(state_hint, MutableMapping):
            state = state_hint
            runtime_mode = True
        else:
            state = load_state()
            runtime_mode = True
    else:
        state = load_state()

    normalized, _active, cls = _prepare_active_storage(dict(state))
    ready_map = normalized.setdefault("ready_target_by_class", {})
    if not isinstance(ready_map, dict):
        ready_map = {}
        normalized["ready_target_by_class"] = ready_map

    target_map = normalized.setdefault("target_monster_id_by_class", {})
    if not isinstance(target_map, dict):
        target_map = {}
        normalized["target_monster_id_by_class"] = target_map

    current_ready = _sanitize_ready_target(ready_map.get(cls))
    current_target = _sanitize_ready_target(target_map.get(cls))
    current = current_ready if current_ready is not None else current_target
    sanitized = _sanitize_ready_target(monster_id)
    if current == sanitized:
        return current, sanitized

    ready_map[cls] = sanitized
    target_map[cls] = sanitized
    active = normalized.get("active")
    if isinstance(active, Mapping):
        active_ready = active.setdefault("ready_target_by_class", {})
        if isinstance(active_ready, dict):
            active_ready[cls] = sanitized
        active_target = active.setdefault("target_monster_id_by_class", {})
        if isinstance(active_target, dict):
            active_target[cls] = sanitized
        active["ready_target"] = sanitized
        active["target_monster_id"] = sanitized

    players = normalized.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            player_class = (
                _normalize_class_name(player.get("class"))
                or _normalize_class_name(player.get("name"))
            )
            if player_class != cls:
                continue
            ready_entry = player.setdefault("ready_target_by_class", {})
            if isinstance(ready_entry, dict):
                ready_entry[cls] = sanitized
            target_entry = player.setdefault("target_monster_id_by_class", {})
            if isinstance(target_entry, dict):
                target_entry[cls] = sanitized
            player["ready_target"] = sanitized
            player["target_monster_id"] = sanitized
            break
    normalized["ready_target_by_class"] = dict(ready_map)
    normalized["target_monster_id_by_class"] = dict(target_map)

    if runtime_mode and ctx is not None:
        ctx["player_state"] = normalized
        ctx.pop(_RUNTIME_PLAYER_KEY, None)
        player_ctx = ensure_player_state(ctx)
        player_ctx["_dirty"] = True
    else:
        save_state(normalized)

    if sanitized:
        _combat_log_set(sanitized, cls)
    elif current:
        _combat_log_clear(reason or "update")
    return current, sanitized


def set_ready_target_for_active(monster_id: Optional[str]) -> Optional[str]:
    """Set the ready target for the active class and persist."""

    _, new_value = _update_ready_target_for_active(monster_id)
    return new_value


def clear_ready_target_for_active(*, reason: Optional[str] = None) -> Optional[str]:
    """Clear the ready target for the active class if set."""

    previous, _ = _update_ready_target_for_active(None, reason=reason or "clear")
    return previous


def clear_target(*, reason: Optional[str] = None) -> Optional[str]:
    """Clear the active ready target and monster aggro references."""

    try:
        state, active = get_active_pair()
    except Exception:
        state, active = get_active_pair()

    reason_token = reason or "clear-target"
    previous = clear_ready_target_for_active(reason=reason_token)

    player_id = _sanitize_player_id(active.get("id") if isinstance(active, Mapping) else None)
    if player_id is None and isinstance(state, Mapping):
        player_id = _sanitize_player_id(state.get("active_id"))

    if player_id is None:
        return previous

    try:
        monsters = monsters_state.load_state()
    except Exception:
        return previous

    cleared = False
    for record in monsters.list_all():
        if not isinstance(record, Mapping):
            continue
        target_token = _sanitize_player_id(record.get("target_player_id"))
        if target_token != player_id:
            continue
        monster_id = (
            record.get("id")
            or record.get("instance_id")
            or record.get("monster_id")
        )
        if not monster_id:
            continue
        monster = monsters.get(str(monster_id))
        if not isinstance(monster, MutableMapping):
            continue
        if _sanitize_player_id(monster.get("target_player_id")) != player_id:
            continue
        monster["target_player_id"] = None
        try:
            monsters.mark_dirty()
        except Exception:
            # Fall back to saving via global dirty flag if marking fails.
            try:
                monsters._track_dirty(str(monster_id))  # type: ignore[attr-defined]
            except Exception:
                pass
        cleared = True

    if cleared:
        try:
            monsters.save()
        except Exception:
            pass

    return previous


def clear_ready_target_for(monster_id: str, *, reason: Optional[str] = None) -> Dict[str, Any]:
    """Clear ready targets referencing ``monster_id`` for all classes."""

    sanitized = _sanitize_ready_target(monster_id)
    if sanitized is None:
        return load_state()

    state = load_state()
    normalized, _active, _cls = _prepare_active_storage(state)
    ready_map = normalized.setdefault("ready_target_by_class", {})
    if not isinstance(ready_map, dict):
        ready_map = {}
        normalized["ready_target_by_class"] = ready_map

    target_map = normalized.setdefault("target_monster_id_by_class", {})
    if not isinstance(target_map, dict):
        target_map = {}
        normalized["target_monster_id_by_class"] = target_map

    changed = False
    for key, value in list(ready_map.items()):
        if _sanitize_ready_target(value) == sanitized:
            ready_map[key] = None
            changed = True
    for key, value in list(target_map.items()):
        if _sanitize_ready_target(value) == sanitized:
            target_map[key] = None
            changed = True

    if not changed:
        return normalized

    normalized["ready_target_by_class"] = dict(ready_map)
    normalized["target_monster_id_by_class"] = dict(target_map)
    save_state(normalized)
    _combat_log_clear(reason or f"match:{sanitized}")
    return normalized


def ensure_active_ready_target_in(
    monster_ids: Iterable[str], *, reason: str = "missing"
) -> Optional[str]:
    """Ensure the active ready target remains within ``monster_ids``."""

    valid_ids = {
        token
        for token in (_sanitize_ready_target(mid) for mid in monster_ids)
        if token
    }
    state = load_state()
    current = get_ready_target_for_active(state)
    if not current:
        return None
    if current not in valid_ids:
        clear_ready_target_for_active(reason=reason)
        return None
    return current


def _copy_status_effects(entries: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    sanitized = _sanitize_status_effect_list(list(entries))
    return [dict(entry) for entry in sanitized]


def get_status_effects_map(
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return a map of status effects keyed by normalized class name."""

    source = state if isinstance(state, dict) else load_state()
    status_map = source.get("status_effects_by_class") if isinstance(source, Mapping) else None
    result: Dict[str, List[Dict[str, Any]]] = {}
    if isinstance(status_map, Mapping):
        for key, payload in status_map.items():
            cls_name = _normalize_class_name(key)
            if not cls_name:
                continue
            result[cls_name] = _copy_status_effects(
                _sanitize_status_effect_list(payload)
            )
    return result


def get_status_effects_for_class(
    class_name: str, *, state: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Return the sanitized status list for ``class_name``."""

    base_state = state if isinstance(state, dict) else load_state()
    target = _normalize_class_name(class_name)
    if not target:
        target = get_active_class(base_state)
    status_map = get_status_effects_map(base_state)
    return [dict(entry) for entry in status_map.get(target, [])]


def set_status_effects_for_class(
    class_name: str,
    statuses: Iterable[Mapping[str, Any]],
    *,
    state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Persist ``statuses`` for ``class_name`` returning the sanitized list."""

    base_state = state if isinstance(state, dict) else load_state()
    normalized, _active, fallback_class = _prepare_active_storage(base_state)
    target = _normalize_class_name(class_name) or fallback_class

    raw_entries = list(statuses) if isinstance(statuses, Iterable) else []
    sanitized = _sanitize_status_effect_list(raw_entries)

    status_map = normalized.setdefault("status_effects_by_class", {})
    if not isinstance(status_map, dict):
        status_map = {}
        normalized["status_effects_by_class"] = status_map

    current = _sanitize_status_effect_list(status_map.get(target))
    if current == sanitized:
        return [dict(entry) for entry in current]

    status_map[target] = sanitized
    save_state(normalized)
    return [dict(entry) for entry in sanitized]


def decrement_status_effects(amount: int = 1) -> Dict[str, List[Dict[str, Any]]]:
    """Decrement durations across all classes, returning expired entries."""

    if amount <= 0:
        return {}

    state = load_state()
    normalized, _active, _klass = _prepare_active_storage(state)
    status_map = normalized.setdefault("status_effects_by_class", {})
    if not isinstance(status_map, dict):
        status_map = {}
        normalized["status_effects_by_class"] = status_map

    expired: Dict[str, List[Dict[str, Any]]] = {}
    changed = False

    for key, payload in list(status_map.items()):
        cls_name = _normalize_class_name(key)
        if not cls_name:
            continue
        entries = _sanitize_status_effect_list(payload)
        updated: List[Dict[str, Any]] = []
        expired_entries: List[Dict[str, Any]] = []
        for entry in entries:
            remaining = max(0, int(entry.get("duration", 0)) - amount)
            if remaining > 0:
                updated.append({"status_id": entry["status_id"], "duration": remaining})
            else:
                expired_entries.append({"status_id": entry["status_id"], "duration": 0})
        if expired_entries:
            expired[cls_name] = expired_entries
        if updated != entries:
            changed = True
        status_map[cls_name] = updated

    if changed:
        normalized["status_effects_by_class"] = status_map
        save_state(normalized)

    return expired


def get_active_pair(
    state: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return a tuple of (state, active_player_dict).

    Falls back to the first player if the active_id cannot be resolved. If no
    players exist, the active portion of the tuple is an empty dict.
    """

    st = state or load_state()
    players = st.get("players")
    if isinstance(players, list) and players:
        aid = st.get("active_id")
        active: Optional[Dict[str, Any]] = None
        for player in players:
            if player.get("id") == aid:
                active = player
                break
        if active is None:
            active = players[0]
        return st, active or {}
    # Legacy single-player format: treat the root state as the active player.
    return st, st


def mutate_active(
    mutator: Callable[[Dict[str, Any], Dict[str, Any]], None]
) -> Dict[str, Any]:
    """Load state, apply ``mutator`` to the active player, and persist.

    ``mutator`` receives the full state and the active player dict. The
    updated state object is returned. If no active player is available the
    mutator is not invoked and the state is returned unchanged.
    """

    state, active = get_active_pair()
    if not active:
        return state
    mutator(state, active)
    save_state(state)
    return state


def _coerce_pos(value: Any) -> Optional[Tuple[int, int, int]]:
    """Return a normalized ``(year, x, y)`` tuple when possible."""

    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except (TypeError, ValueError):
            return None
    return None


def _infer_class_from_ctx(ctx: Any) -> Optional[str]:
    """Best-effort extraction of a class name from an execution context."""

    if ctx is None:
        return None

    if hasattr(ctx, "session"):
        session_obj = getattr(ctx, "session", None)
        candidate = getattr(session_obj, "active_class", None)
        if isinstance(candidate, str) and candidate:
            return candidate

    if isinstance(ctx, dict) and "session" in ctx:
        session_payload = ctx["session"]
        if isinstance(session_payload, dict):
            candidate = session_payload.get("active_class")
            if isinstance(candidate, str) and candidate:
                return candidate

    def _pull(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    for key in ("player", "active"):
        payload = _pull(ctx, key)
        if isinstance(payload, dict):
            klass = payload.get("class") or payload.get("name")
            if isinstance(klass, str) and klass:
                return klass

    candidate = _pull(ctx, "class_name")
    if isinstance(candidate, str) and candidate:
        return candidate

    return None


def _infer_pos_from_ctx(ctx: Any) -> Optional[Tuple[int, int, int]]:
    """Try to recover a position triple from assorted context hints."""

    if ctx is None:
        return None

    def _pull(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    for key in ("pos", "position"):
        pos = _coerce_pos(_pull(ctx, key))
        if pos:
            return pos

    player_state = _pull(ctx, "player_state")
    if isinstance(player_state, dict):
        active_id = player_state.get("active_id")
        players = player_state.get("players")
        if isinstance(players, list) and players:
            chosen: Optional[Dict[str, Any]] = None
            for candidate in players:
                if not isinstance(candidate, dict):
                    continue
                if active_id is None or candidate.get("id") == active_id:
                    chosen = candidate
                    break
            if chosen is None:
                first = players[0]
                chosen = first if isinstance(first, dict) else None
            if isinstance(chosen, dict):
                for key in ("pos", "position"):
                    pos = _coerce_pos(chosen.get(key))
                    if pos:
                        return pos
        for key in ("pos", "position"):
            pos = _coerce_pos(player_state.get(key))
            if pos:
                return pos

    world = _pull(ctx, "world")
    if isinstance(world, dict):
        for key in ("pos", "position"):
            pos = _coerce_pos(world.get(key))
            if pos:
                return pos

    return None


def ensure_active_profile(player: Dict[str, Any], ctx: Any) -> None:
    """Ensure ``player['active']`` has a class and position derived from context."""

    active = player.get("active")
    if not isinstance(active, dict):
        active = {}
        player["active"] = active

    klass_candidate = active.get("class")
    klass = klass_candidate if isinstance(klass_candidate, str) and klass_candidate else None
    if not klass:
        candidate = player.get("class") or player.get("name")
        if isinstance(candidate, str) and candidate:
            klass = candidate
    if not klass:
        inferred = _infer_class_from_ctx(ctx)
        if isinstance(inferred, str) and inferred:
            klass = inferred
    if not klass:
        klass = "Thief"
    active["class"] = klass
    if "class" not in player or not player.get("class"):
        player["class"] = klass

    pos = _coerce_pos(active.get("pos"))
    if pos is None:
        pos = _infer_pos_from_ctx(ctx)
    if pos is None:
        pos = _coerce_pos(player.get("pos")) or _coerce_pos(player.get("position"))
    if pos is None:
        year = player.get("year")
        try:
            year_val = int(year)
        except Exception:
            year_val = 2000
        pos = (year_val, 0, 0)
    active["pos"] = [int(pos[0]), int(pos[1]), int(pos[2])]
    if "pos" not in player or _coerce_pos(player.get("pos")) is None:
        player["pos"] = list(active["pos"])


def bind_inventory_to_active_class(player: Dict[str, Any]) -> None:
    """Bind ``player['inventory']`` to a per-class bag under ``player['bags']``."""

    active = player.get("active")
    if not isinstance(active, dict):
        active = {}
        player["active"] = active

    klass_raw = active.get("class") or player.get("class") or player.get("name")
    if isinstance(klass_raw, str) and klass_raw:
        klass = klass_raw
    else:
        klass = "Thief"
    active["class"] = klass
    if "class" not in player or not player.get("class"):
        player["class"] = klass

    bags = player.get("bags")
    if not isinstance(bags, dict):
        bags = {}
        player["bags"] = bags

    inventory = player.get("inventory")
    inv_list = list(inventory) if isinstance(inventory, list) else []

    equipped = get_equipped_armour_id(player)
    if not equipped and isinstance(active, dict):
        equipped = get_equipped_armour_id(active)

    bag = bags.get(klass)
    if isinstance(bag, list):
        if inv_list and bag is not inv_list:
            for item in inv_list:
                if item and item not in bag:
                    bag.append(item)
    else:
        bag = [item for item in inv_list if item]

    wielded = None
    raw_wield_map = player.get("wielded_by_class")
    if isinstance(raw_wield_map, Mapping):
        wielded = _sanitize_equipped_iid(raw_wield_map.get(klass))
    if not wielded and isinstance(active, Mapping):
        active_wield_map = active.get("wielded_by_class")
        if isinstance(active_wield_map, Mapping):
            wielded = _sanitize_equipped_iid(active_wield_map.get(klass))
    if not wielded:
        wielded = _sanitize_equipped_iid(player.get("wielded"))
    if not wielded and isinstance(active, Mapping):
        wielded = _sanitize_equipped_iid(active.get("wielded"))
    if wielded and wielded not in bag:
        wielded = None

    bags[klass] = bag
    player["inventory"] = bag
    active["inventory"] = bag

    equipment_map = player.setdefault("equipment_by_class", {})
    if isinstance(equipment_map, dict):
        equipment_map[klass] = {"armour": equipped}
    if isinstance(active, dict):
        active_equipment = active.setdefault("equipment_by_class", {})
        if isinstance(active_equipment, dict):
            active_equipment[klass] = {"armour": equipped}
    _set_armour_view(player, equipped)
    _set_armour_view(active, equipped)

    player_wield_map = player.setdefault("wielded_by_class", {})
    if isinstance(player_wield_map, dict):
        player_wield_map[klass] = wielded
    if isinstance(active, dict):
        active_wield_map = active.setdefault("wielded_by_class", {})
        if isinstance(active_wield_map, dict):
            active_wield_map[klass] = wielded
    _set_wield_view(player, wielded)
    _set_wield_view(active, wielded)


def _save_player(state: Dict[str, Any]) -> None:
    """Persist ``state`` ensuring critical invariants are respected."""

    ensure_active_profile(state, ctx={})
    bind_inventory_to_active_class(state)

    active = state.get("active")
    klass = "Thief"
    if isinstance(active, dict):
        klass = str(active.get("class") or state.get("class") or "Thief")
    bags = state.setdefault("bags", {})
    inventory = state.get("inventory")
    bags[klass] = list(inventory) if isinstance(inventory, list) else []

    save_state(state)
