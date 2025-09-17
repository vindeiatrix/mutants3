"""State management for player templates, save files, and live runtime."""
from __future__ import annotations

import json
import logging
import os
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from mutants.engine.game_state import (
    PlayerTemplate,
    PlayerState,
    SaveData,
    deep_copy_from_template,
)
from mutants.io.atomic import atomic_write_json
from mutants.persistence.paths import TEMPLATE_PATH, SAVE_PATH, ensure_state_root


LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 1


KNOWN_CLASS_ORDER = [
    "player_thief",
    "player_priest",
    "player_wizard",
    "player_warrior",
    "player_mage",
]


@dataclass
class LoadResult:
    save_data: SaveData
    created: bool


def _now_ts() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _deep_merge(base: Mapping[str, Any], overrides: Mapping[str, Any] | None) -> Dict[str, Any]:
    merged = deepcopy(base)
    if not isinstance(overrides, Mapping):
        return merged
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _normalize_pos(value: Any, fallback: Iterable[int]) -> List[int]:
    fallback_list = list(fallback)
    if isinstance(value, Mapping):
        cand = [value.get("year"), value.get("x"), value.get("y")]
    elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        cand = list(value)
    else:
        cand = list(fallback_list)

    norm: List[int] = []
    for idx in range(3):
        try:
            norm.append(int(cand[idx]))
        except (TypeError, ValueError, IndexError):
            norm.append(int(fallback_list[idx] if idx < len(fallback_list) else 0))
    return norm


def _sanitize_player_dict(raw: Mapping[str, Any], template: Mapping[str, Any]) -> Dict[str, Any]:
    data = deepcopy(raw)

    defaults = deepcopy(template)

    # Nested dicts: merge defaults to ensure required keys exist.
    for key in ("hp", "stats", "conditions"):
        template_val = defaults.get(key) or {}
        if key in data and isinstance(data[key], Mapping):
            data[key] = _deep_merge(template_val, data[key])
        else:
            data[key] = deepcopy(template_val)

    # Inventory must be a list.
    inv = data.get("inventory")
    if not isinstance(inv, list):
        data["inventory"] = list(defaults.get("inventory", []))

    # Position normalization.
    data["pos"] = _normalize_pos(data.get("pos"), defaults.get("pos", [2000, 0, 0]))

    # Conditions should be booleans.
    conds = data.get("conditions", {})
    if isinstance(conds, dict):
        for name, value in list(conds.items()):
            conds[name] = bool(value)

    # Scalar ints.
    for key in ("level", "exp_points", "exp", "exhaustion", "ions", "riblets"):
        if key in data:
            try:
                data[key] = int(data[key])
            except (TypeError, ValueError):
                data[key] = int(defaults.get(key, 0))
        else:
            data[key] = int(defaults.get(key, 0))

    state = PlayerState(data)
    state.clamp()
    return state.to_dict()


def _backup_corrupt(path: Path) -> None:
    try:
        ts = time.strftime("%Y%m%d%H%M%S")
        backup = path.with_suffix(path.suffix + f".bak.{ts}")
        os.replace(path, backup)
        LOG.warning("Backed up corrupt save to %s", backup)
    except Exception:
        LOG.exception("Failed to back up corrupt save %s", path)


class StateManager:
    """Manage templates, persistent save data, and live runtime state."""

    def __init__(
        self,
        template_path: str | Path = TEMPLATE_PATH,
        save_path: str | Path = SAVE_PATH,
        autosave_interval: int | None = None,
    ) -> None:
        ensure_state_root()
        self.template_path = Path(template_path)
        self.save_path = Path(save_path)
        self.autosave_interval = max(0, int(autosave_interval or 0))
        self.command_counter = 0
        self.dirty = False

        LOG.info("Loading player templates from %s", self.template_path)
        self.templates = self.load_template(self.template_path)
        self.template_order = [cid for cid in KNOWN_CLASS_ORDER if cid in self.templates]

        load_result = self.load_or_init_save(self.templates, self.save_path)
        self.save_data = load_result.save_data
        self.dirty = False

        # Legacy dict exposed to the rest of the codebase.
        self._legacy_state: Dict[str, Any] = {"players": [], "active_id": self.save_data.active_id}
        self._legacy_players: List[Dict[str, Any]] = self._legacy_state["players"]
        self._sync_legacy_views()

        if load_result.created:
            LOG.info("Created new save at %s", self.save_path)
            self.persist()

    # ------------------------------------------------------------------
    @staticmethod
    def load_template(path: str | Path) -> Dict[str, PlayerTemplate]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Template not found at {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        players = data.get("players")
        if not isinstance(players, list):
            raise ValueError("Template missing 'players' list")

        templates: Dict[str, PlayerTemplate] = {}
        missing: List[str] = []
        for cid in KNOWN_CLASS_ORDER:
            found = None
            for entry in players:
                if entry.get("id") == cid:
                    found = entry
                    break
            if not found:
                missing.append(cid)
                continue
            templates[cid] = PlayerTemplate(class_id=cid, data=_sanitize_player_dict(found, found))

        if missing:
            raise ValueError(f"Template missing classes: {', '.join(missing)}")

        # Warn about extras.
        for entry in players:
            cid = entry.get("id")
            if cid not in KNOWN_CLASS_ORDER:
                LOG.warning("Ignoring unknown class '%s' in template", cid)
        return templates

    # ------------------------------------------------------------------
    @staticmethod
    def load_or_init_save(
        templates: Mapping[str, PlayerTemplate], save_path: str | Path
    ) -> LoadResult:
        p = Path(save_path)
        if not p.exists():
            LOG.info("No save found at %s; generating from templates", p)
            return LoadResult(
                save_data=_build_save_from_templates(templates),
                created=True,
            )

        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            LOG.warning("Failed to read save %s (%s); rebuilding", p, exc)
            _backup_corrupt(p)
            return LoadResult(
                save_data=_build_save_from_templates(templates),
                created=True,
            )

        try:
            meta = raw.get("meta") or {}
            version = int(meta.get("schema_version", 0))
            if version != SCHEMA_VERSION:
                raise ValueError(f"Unsupported schema_version {version}")
            players_raw = raw.get("players")
            if not isinstance(players_raw, Mapping):
                raise ValueError("Save missing 'players' mapping")
        except Exception as exc:
            LOG.warning("Invalid save structure; rebuilding (%s)", exc)
            _backup_corrupt(p)
            return LoadResult(
                save_data=_build_save_from_templates(templates),
                created=True,
            )

        players: Dict[str, PlayerState] = {}
        for cid, template in templates.items():
            raw_player = players_raw.get(cid)
            if isinstance(raw_player, Mapping):
                players[cid] = PlayerState(_sanitize_player_dict(raw_player, template.data))
            else:
                LOG.warning("Missing player '%s' in save; recreating from template", cid)
                players[cid] = deep_copy_from_template(template)

        active_id = raw.get("active_id")
        if active_id not in players:
            fallback = next(iter(players)) if players else None
            if fallback:
                LOG.warning("Active player '%s' invalid; defaulting to %s", active_id, fallback)
                active_id = fallback
            else:
                active_id = ""
        save_meta = {
            "schema_version": SCHEMA_VERSION,
            "created_at": meta.get("created_at") or _now_ts(),
            "updated_at": meta.get("updated_at") or _now_ts(),
        }
        return LoadResult(save_data=SaveData(meta=save_meta, players=players, active_id=active_id), created=False)

    # ------------------------------------------------------------------
    def _sync_legacy_views(self) -> None:
        self._legacy_players.clear()
        for cid in self.template_order:
            ps = self.save_data.players.get(cid)
            if ps:
                self._legacy_players.append(ps.to_dict())
        self._legacy_state["active_id"] = self.save_data.active_id

    @property
    def legacy_state(self) -> Dict[str, Any]:
        return self._legacy_state

    @property
    def active_id(self) -> str:
        return self.save_data.active_id

    def get_active(self) -> PlayerState:
        return self.save_data.players[self.save_data.active_id]

    def switch_active(self, class_id: str) -> None:
        if class_id not in self.save_data.players:
            raise KeyError(class_id)
        if class_id == self.save_data.active_id:
            LOG.info("Class '%s' already active", class_id)
            return
        LOG.info("Switching active class to %s", class_id)
        self.save_data.active_id = class_id
        self.dirty = True
        self._sync_legacy_views()
        self.persist()

    def reset_player(self, class_id: str) -> str:
        if class_id not in self.save_data.players:
            raise KeyError(class_id)
        return "Bury not implemented yet."

    def persist(self) -> None:
        payload = self._serialize()
        updated = _now_ts()
        payload["meta"]["updated_at"] = updated
        self.save_data.meta.update(payload["meta"])
        atomic_write_json(self.save_path, payload)
        LOG.info("Saved game state to %s", self.save_path)
        self.dirty = False
        self.command_counter = 0

    def mark_dirty(self) -> None:
        self.dirty = True

    def on_command_executed(self, command_name: str | None = None) -> None:
        if not command_name:
            return
        self.command_counter += 1
        if self.autosave_interval and self.dirty and self.command_counter >= self.autosave_interval:
            LOG.info("Autosave triggered after %s commands", self.command_counter)
            self.persist()

    def save_on_exit(self) -> None:
        if self.dirty:
            LOG.info("Saving on exit")
            self.persist()

    def _serialize(self) -> Dict[str, Any]:
        players_out = {
            cid: player.to_dict()
            for cid, player in self.save_data.players.items()
        }
        meta = dict(self.save_data.meta)
        meta.setdefault("schema_version", SCHEMA_VERSION)
        meta.setdefault("created_at", _now_ts())
        meta.setdefault("updated_at", _now_ts())
        return {"meta": meta, "players": players_out, "active_id": self.save_data.active_id}


def _build_save_from_templates(templates: Mapping[str, PlayerTemplate]) -> SaveData:
    players = {cid: deep_copy_from_template(tpl) for cid, tpl in templates.items()}
    active_id = next(iter(players)) if players else ""
    meta = {"schema_version": SCHEMA_VERSION, "created_at": _now_ts(), "updated_at": _now_ts()}
    return SaveData(meta=meta, players=players, active_id=active_id)

