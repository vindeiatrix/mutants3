from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from mutants.services import monsters_state, player_state

LOG = logging.getLogger(__name__)


class StatusManager:
    """Manage timed status effects for player classes and monsters."""

    def __init__(
        self,
        *,
        player_loader=player_state.load_state,
        monster_loader=monsters_state.load_state,
    ) -> None:
        self._load_player_state = player_loader
        self._load_monster_state = monster_loader

    def apply(self, entity_id: str, status_id: str, duration: int) -> List[Dict[str, Any]]:
        """Apply or update a status for ``entity_id``."""

        kind, token = self._normalize_entity(entity_id)
        if kind == "player":
            return self._apply_to_player(token, status_id, duration)
        if kind == "monster":
            return self._apply_to_monster(token, status_id, duration)
        raise ValueError(f"Unsupported entity type for {entity_id!r}")

    def tick(self, amount: int = 1) -> None:
        """Advance all status timers by ``amount`` turns (default: 1)."""

        if amount <= 0:
            return

        try:
            player_state.decrement_status_effects(amount)
        except Exception:  # pragma: no cover - defensive logging
            LOG.exception("Failed to decrement player status effects")

        try:
            monsters = self._load_monster_state()
            monsters.decrement_status_effects(amount)
        except Exception:  # pragma: no cover - defensive logging
            LOG.exception("Failed to decrement monster status effects")

    # Internal helpers -------------------------------------------------
    def _apply_to_player(
        self, class_token: str, status_id: str, duration: int
    ) -> List[Dict[str, Any]]:
        state = self._load_player_state()
        target = player_state.normalize_class_name(class_token)
        if not target:
            target = self._resolve_player_class_from_id(state, class_token)
        existing = player_state.get_status_effects_for_class(target, state=state)
        merged = self._merge_entries(existing, status_id, duration)
        return player_state.set_status_effects_for_class(target, merged, state=state)

    def _apply_to_monster(
        self, monster_id: str, status_id: str, duration: int
    ) -> List[Dict[str, Any]]:
        monsters = self._load_monster_state()
        monster = monsters.get(monster_id)
        if monster is None:
            raise KeyError(monster_id)
        existing = monster.get("status_effects") or []
        merged = self._merge_entries(existing, status_id, duration)
        result = monsters.set_status_effects(monster_id, merged)
        monsters.save()
        return result

    def _resolve_player_class_from_id(
        self, state: Mapping[str, Any], token: str
    ) -> str:
        players = state.get("players") if isinstance(state, Mapping) else None
        if isinstance(players, list):
            for player in players:
                if not isinstance(player, Mapping):
                    continue
                if str(player.get("id")) != token:
                    continue
                cls = player_state.normalize_class_name(player.get("class"))
                if not cls:
                    cls = player_state.normalize_class_name(player.get("name"))
                if cls:
                    return cls
        return player_state.get_active_class(state if isinstance(state, dict) else {})

    def _merge_entries(
        self, statuses: Iterable[Mapping[str, Any]], status_id: str, duration: int
    ) -> List[Dict[str, Any]]:
        normalized_id = self._normalize_status_id(status_id)
        target_duration = max(0, self._coerce_int(duration))

        merged: List[Dict[str, Any]] = []
        seen = False
        for entry in statuses:
            if not isinstance(entry, Mapping):
                continue
            entry_id = entry.get("status_id")
            normalized_entry = self._normalize_status_id(entry_id) if entry_id else None
            if not normalized_entry:
                continue
            current = max(0, self._coerce_int(entry.get("duration")))
            if normalized_entry == normalized_id:
                seen = True
                if target_duration > 0:
                    merged.append({"status_id": normalized_id, "duration": target_duration})
                continue
            merged.append({"status_id": normalized_entry, "duration": current})

        if not seen and target_duration > 0:
            merged.append({"status_id": normalized_id, "duration": target_duration})

        return merged

    def _normalize_entity(self, entity_id: str) -> Tuple[str, str]:
        token = (entity_id or "").strip()
        if not token:
            raise ValueError("entity_id must be a non-empty string")

        lower = token.lower()
        if lower.startswith("monster:"):
            return "monster", token.split(":", 1)[1].strip()
        if lower.startswith("player:") or lower.startswith("class:"):
            return "player", token.split(":", 1)[1].strip()
        if "#" in token:
            return "monster", token
        return "player", token

    def _normalize_status_id(self, status_id: Any) -> str:
        if isinstance(status_id, str):
            token = status_id.strip()
        elif status_id is None:
            token = ""
        else:
            token = str(status_id).strip()
        if not token:
            raise ValueError("status_id must be provided")
        return token

    @staticmethod
    def _coerce_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
