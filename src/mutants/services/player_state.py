from __future__ import annotations
import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from mutants.io.atomic import atomic_write_json


LOG_P = logging.getLogger("mutants.playersdbg")


_PDBG_CONFIGURED = False


def _pdbg_setup_file_logging() -> None:
    """Send playersdbg logs to a file when debugging is enabled."""

    global _PDBG_CONFIGURED
    if _PDBG_CONFIGURED or not _pdbg_enabled():
        return
    try:
        log_dir = Path("state") / "logs"
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
    return bool(os.environ.get("PLAYERS_DEBUG"))


def _playersdbg_log(action: str, state: Dict[str, Any]) -> None:
    if not _pdbg_enabled() or not isinstance(state, dict):
        return
    _pdbg_setup_file_logging()
    try:
        active = state.get("active")
        if not isinstance(active, dict):
            active = {}
        klass = active.get("class") or state.get("class") or "?"
        inventory: List[str] = []
        raw_inv = state.get("inventory")
        if not isinstance(raw_inv, list):
            raw_inv = active.get("inventory") if isinstance(active, dict) else None
        if isinstance(raw_inv, list):
            inventory = [str(i) for i in raw_inv if i is not None]
        LOG_P.info(
            "[playersdbg] %s class=%s path=%s inv_iids=%s pos=%s ions=%s",
            action,
            klass,
            str(_player_path()),
            inventory,
            active.get("pos"),
            state.get("Ions", state.get("ions")),
        )
    except Exception:  # pragma: no cover - defensive logging only
        pass

def _player_path() -> Path:
    return Path(os.getcwd()) / "state" / "playerlivestate.json"


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

    bags = state.get("bags")
    if not isinstance(bags, dict):
        bags = {}
        state["bags"] = bags
        bag = list(cleaned_inventory)
    else:
        existing_bag = bags.get(klass)
        if isinstance(existing_bag, list):
            bag = [item for item in existing_bag if item is not None]
        else:
            bag = []

    bags[klass] = bag
    state["inventory"] = bags[klass]
    active["inventory"] = bags[klass]

    # 4) normalize per-class currencies
    def _normalize_currency(
        key: str, fallback_keys: Tuple[str, ...]
    ) -> Dict[str, int]:
        raw_map = state.get(key)
        normalized: Dict[str, int] = {}
        if isinstance(raw_map, dict):
            for name, value in raw_map.items():
                if not isinstance(name, str) or not name:
                    continue
                normalized[name] = _coerce_int(value, 0)
        state[key] = normalized

        current = normalized.get(klass)
        if current is None:
            fallback: Any = None
            # try values on the active profile first
            if isinstance(active, dict):
                for fk in fallback_keys:
                    fallback = active.get(fk.lower())
                    if fallback is not None:
                        break
                    fallback = active.get(fk)
                    if fallback is not None:
                        break
            if fallback is None:
                for fk in fallback_keys:
                    if fk in state:
                        fallback = state.get(fk)
                        if fallback is not None:
                            break
            normalized[klass] = _coerce_int(fallback, 0)
        else:
            normalized[klass] = _coerce_int(current, 0)

        lower_name = fallback_keys[0]
        upper_name = fallback_keys[-1]
        if isinstance(active, dict):
            active[lower_name] = normalized[klass]
        state[lower_name] = normalized[klass]
        state[upper_name] = normalized[klass]
        return normalized

    _normalize_currency("ions_by_class", ("ions", "Ions"))
    _normalize_currency("riblets_by_class", ("riblets", "Riblets"))

    return state


def load_state() -> Dict[str, Any]:
    path = _player_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            state: Dict[str, Any] = json.load(f)
        before = json.dumps(state, sort_keys=True, ensure_ascii=False)
        normalized = _normalize_player_state(state)
        after = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        if after != before:
            _persist_canonical(normalized)
        state = normalized
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"players": [], "active_id": None}
    _playersdbg_log("LOAD", state)
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
    normalized = _normalize_player_state(to_save)
    _persist_canonical(normalized)
    _playersdbg_log("SAVE", normalized)


def get_active_class(state: Dict[str, Any]) -> str:
    """Return the class name for the active player in ``state``."""

    if not isinstance(state, dict):
        return "Thief"
    active = state.get("active")
    if isinstance(active, dict):
        klass = active.get("class") or active.get("name")
        if isinstance(klass, str) and klass:
            return klass
    fallback = state.get("class") or state.get("name")
    if isinstance(fallback, str) and fallback:
        return fallback
    return "Thief"


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

    normalized = _normalize_player_state(state)
    cls = get_active_class(normalized)
    rib_map = normalized.setdefault("riblets_by_class", {})
    new_total = max(0, _coerce_int(amount, 0))
    rib_map[cls] = new_total

    active = normalized.get("active")
    if isinstance(active, dict):
        active["riblets"] = new_total
    normalized["riblets"] = new_total
    normalized["Riblets"] = new_total

    save_state(normalized)
    return new_total


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

    bag = bags.get(klass)
    if isinstance(bag, list):
        if inv_list and bag is not inv_list:
            for item in inv_list:
                if item and item not in bag:
                    bag.append(item)
    else:
        bag = [item for item in inv_list if item]

    bags[klass] = bag
    player["inventory"] = bag
    active["inventory"] = bag


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
