"""Helpers for handling player death and respawn sequences."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, MutableMapping, Sequence

from mutants.players import startup as player_startup
from mutants.services import player_state as pstate


LOG = logging.getLogger(__name__)

_DEFAULT_RESPAWN_POS = (2000, 0, 0)


class _MonsterLedger:
    """Helpers for updating a monster's ion and riblet ledger."""

    @staticmethod
    def _ensure_container(
        monster: MutableMapping[str, Any], key: str
    ) -> MutableMapping[str, Any]:
        payload = monster.get(key)
        if isinstance(payload, MutableMapping):
            return payload
        if isinstance(payload, Mapping):
            container = dict(payload)
        else:
            container = {}
        monster[key] = container
        return container

    def deposit(
        self,
        monster: MutableMapping[str, Any] | Mapping[str, Any] | None,
        *,
        ions: Any = 0,
        riblets: Any = 0,
    ) -> Dict[str, int]:
        """Deposit currencies into ``monster``'s ledger.

        The ledger is stored under ``monster["_ai_state"]["ledger"]`` and mirrored on the
        top-level ``monster`` mapping to keep persistence helpers in sync.
        """

        if not isinstance(monster, MutableMapping):
            return {"ions": 0, "riblets": 0}

        ai_state = self._ensure_container(monster, "_ai_state")
        ledger = self._ensure_container(ai_state, "ledger")

        base_ions = _coerce_int(ledger.get("ions"), _coerce_int(monster.get("ions"), 0))
        base_riblets = _coerce_int(
            ledger.get("riblets"), _coerce_int(monster.get("riblets"), 0)
        )

        deposit_ions = max(0, _coerce_int(ions, 0))
        deposit_riblets = max(0, _coerce_int(riblets, 0))

        total_ions = base_ions + deposit_ions
        total_riblets = base_riblets + deposit_riblets

        ledger["ions"] = total_ions
        ledger["riblets"] = total_riblets
        monster["ions"] = total_ions
        monster["riblets"] = total_riblets

        return {"ions": total_ions, "riblets": total_riblets}


monster_ledger = _MonsterLedger()


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ensure_mutable_map(scope: MutableMapping[str, Any], key: str) -> MutableMapping[str, Any]:
    payload = scope.get(key)
    if isinstance(payload, MutableMapping):
        return payload
    mapping: MutableMapping[str, Any] = {}
    scope[key] = mapping
    return mapping


def _coerce_pos(pos: Sequence[Any] | None) -> list[int]:
    base = list(_DEFAULT_RESPAWN_POS)
    if not pos:
        return base
    result: list[int] = []
    for idx in range(3):
        try:
            value = pos[idx]
        except (IndexError, TypeError):
            result.append(base[idx])
            continue
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            result.append(base[idx])
    return result


def _transfer_currency_to_monster(
    monster: Mapping[str, Any] | MutableMapping[str, Any] | None,
    ions: int,
    riblets: int,
) -> None:
    """Backward-compatible helper routing through :mod:`monster_ledger`."""

    monster_ledger.deposit(monster, ions=ions, riblets=riblets)


def _clear_player_inventory(
    state: MutableMapping[str, Any],
    active: MutableMapping[str, Any],
    cls: str,
) -> None:
    scopes: list[MutableMapping[str, Any]] = [state]
    if isinstance(active, MutableMapping):
        scopes.append(active)

    players = state.get("players")
    if isinstance(players, list):
        for player in players:
            if isinstance(player, MutableMapping):
                scopes.append(player)

    for scope in scopes:
        bags = _ensure_mutable_map(scope, "bags")
        bags[cls] = []

        bags_by_class = scope.get("bags_by_class")
        if isinstance(bags_by_class, MutableMapping):
            bags_by_class[cls] = []

        scope["inventory"] = []

        equipment = scope.get("equipment_by_class")
        if isinstance(equipment, MutableMapping):
            equipment[cls] = {"armour": None}

        wielded_map = scope.get("wielded_by_class")
        if isinstance(wielded_map, MutableMapping):
            wielded_map[cls] = None

        scope["wielded"] = None

        armour = scope.get("armour")
        if isinstance(armour, MutableMapping):
            armour["wearing"] = None
        elif armour is not None:
            scope["armour"] = {"wearing": None}


def _clear_ready_target(
    state: MutableMapping[str, Any],
    active: MutableMapping[str, Any],
    cls: str,
) -> None:
    ready_map = _ensure_mutable_map(state, "ready_target_by_class")
    ready_map[cls] = None

    target_map = _ensure_mutable_map(state, "target_monster_id_by_class")
    target_map[cls] = None

    state["ready_target"] = None
    state["target_monster_id"] = None

    mirrors = [active]
    root_active = state.get("active")
    if isinstance(root_active, MutableMapping) and root_active is not active:
        mirrors.append(root_active)

    for scope in mirrors:
        scope["ready_target"] = None
        scope["target_monster_id"] = None
        ready_by_class = scope.get("ready_target_by_class")
        if isinstance(ready_by_class, MutableMapping):
            ready_by_class[cls] = None
        target_by_class = scope.get("target_monster_id_by_class")
        if isinstance(target_by_class, MutableMapping):
            target_by_class[cls] = None


def _reset_riblets(
    state: MutableMapping[str, Any],
    active: MutableMapping[str, Any],
    cls: str,
) -> None:
    rib_map = _ensure_mutable_map(state, "riblets_by_class")
    rib_map[cls] = 0

    mirrors = [state, active]
    root_active = state.get("active")
    if isinstance(root_active, MutableMapping) and root_active not in mirrors:
        mirrors.append(root_active)

    players = state.get("players")
    if isinstance(players, list):
        for player in players:
            if isinstance(player, MutableMapping) and player not in mirrors:
                mirrors.append(player)

    for scope in mirrors:
        scope["riblets"] = 0
        scope["Riblets"] = 0
        riblets_map = scope.get("riblets_by_class")
        if isinstance(riblets_map, MutableMapping):
            riblets_map[cls] = 0


def _resolve_max_hp(
    state: Mapping[str, Any], active: Mapping[str, Any], cls: str
) -> int:
    max_hp = 0
    hp_block = active.get("hp") if isinstance(active, Mapping) else None
    if isinstance(hp_block, Mapping):
        max_hp = max(max_hp, _coerce_int(hp_block.get("max"), 0))
        if max_hp <= 0:
            max_hp = max(max_hp, _coerce_int(hp_block.get("current"), 0))

    hp_map = state.get("hp_by_class")
    if isinstance(hp_map, Mapping):
        entry = hp_map.get(cls)
        if isinstance(entry, Mapping):
            max_hp = max(max_hp, _coerce_int(entry.get("max"), 0))
            if max_hp <= 0:
                max_hp = max(max_hp, _coerce_int(entry.get("current"), 0))

    return max_hp if max_hp > 0 else 1


def _reset_hp(
    state: MutableMapping[str, Any],
    active: MutableMapping[str, Any],
    cls: str,
    maximum: int,
) -> None:
    block = {"current": maximum, "max": maximum}

    active["hp"] = dict(block)
    state["hp"] = dict(block)

    root_active = state.get("active")
    if isinstance(root_active, MutableMapping):
        root_active["hp"] = dict(block)

    hp_map = _ensure_mutable_map(state, "hp_by_class")
    hp_map[cls] = dict(block)


def _reset_position(
    state: MutableMapping[str, Any],
    active: MutableMapping[str, Any],
    pos: Sequence[Any] | None,
) -> None:
    resolved = _coerce_pos(pos)
    active["pos"] = list(resolved)
    state["pos"] = list(resolved)

    root_active = state.get("active")
    if isinstance(root_active, MutableMapping):
        root_active["pos"] = list(resolved)


def handle_player_death(
    player_id: str | None,
    killer_monster: Mapping[str, Any] | MutableMapping[str, Any] | None,
    *,
    state: MutableMapping[str, Any] | None = None,
    active: MutableMapping[str, Any] | None = None,
    respawn_pos: Sequence[Any] | None = None,
) -> MutableMapping[str, Any]:
    """Respawn the slain player and transfer currencies to the killer."""

    state_obj: MutableMapping[str, Any]
    active_obj: MutableMapping[str, Any]

    if isinstance(state, MutableMapping) and isinstance(active, MutableMapping):
        state_obj, active_obj = state, active
    else:
        state_obj, active_obj = pstate.get_active_pair(state)

    if not isinstance(state_obj, MutableMapping) or not isinstance(active_obj, MutableMapping):
        LOG.warning("player_death.handle_player_death: missing mutable state")
        return state_obj

    try:
        monsters_ctx = ctx.get("monsters") if isinstance(ctx, Mapping) else None
        pstate.clear_target(reason="player-death", monsters=monsters_ctx)
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to clear ready target after player death")

    if player_id:
        players = state_obj.get("players")
        if isinstance(players, list):
            for entry in players:
                if not isinstance(entry, MutableMapping):
                    continue
                if str(entry.get("id") or "") == str(player_id):
                    active_obj = entry
                    break

    cls = active_obj.get("class") or active_obj.get("name")
    if not isinstance(cls, str) or not cls:
        cls = pstate.get_active_class(state_obj)
    if not isinstance(cls, str) or not cls:
        cls = "Thief"

    previous_ions = pstate.get_ions_for_active(state_obj)
    previous_riblets = pstate.get_riblets_for_active(state_obj)

    _clear_player_inventory(state_obj, active_obj, cls)
    _clear_ready_target(state_obj, active_obj, cls)
    _reset_riblets(state_obj, active_obj, cls)

    try:
        starting_amount = player_startup.grant_starting_ions(active_obj, "fresh", state=state_obj)
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to grant starting ions during respawn; using fallback amount")
        starting_amount = player_startup.START_IONS.get("fresh", 30_000)
        active_obj["ions"] = starting_amount
        active_obj["Ions"] = starting_amount
        state_obj["ions"] = starting_amount
        state_obj["Ions"] = starting_amount

    max_hp = _resolve_max_hp(state_obj, active_obj, cls)
    _reset_hp(state_obj, active_obj, cls, max_hp)
    _reset_position(state_obj, active_obj, respawn_pos or _DEFAULT_RESPAWN_POS)

    LOG.info(
        "Player %s respawned at %s with %d ions after death (lost ions=%d riblets=%d)",
        player_id or "<active>",
        active_obj.get("pos"),
        starting_amount,
        previous_ions,
        previous_riblets,
    )

    pstate.save_state(state_obj)
    return state_obj


__all__ = ["handle_player_death", "monster_ledger"]
