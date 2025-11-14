from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any, Callable, Mapping, MutableMapping, Optional, Sequence

from mutants.debug import turnlog
if TYPE_CHECKING:
    from mutants.services.status_manager import StatusManager
from mutants.services import random_pool
from mutants.services.combat_config import CombatConfig

LOG = logging.getLogger(__name__)

__all__ = ["TurnScheduler"]

_MISSING = object()


class TurnScheduler:
    """Coordinate deterministic turn ticks between players and monsters."""

    def __init__(
        self,
        ctx: Any,
        *,
        rng_name: str = "turn",
        status_manager: Optional["StatusManager"] = None,
    ) -> None:
        self._ctx = ctx
        self._rng_name = rng_name
        if status_manager is None:
            from mutants.services.status_manager import StatusManager as _StatusManager

            self._status_manager: Optional["StatusManager"] = _StatusManager()
        else:
            self._status_manager = status_manager
        self._free_actions: list[Callable[[Any], None]] = []

    # Internal state helpers --------------------------------------------
    def _monster_id(self, monster: Mapping[str, Any] | None) -> str:
        if not isinstance(monster, Mapping):
            return ""
        for key in ("id", "instance_id", "monster_id"):
            raw = monster.get(key)
            if raw is None:
                continue
            token = str(raw).strip()
            if token:
                return token
        return ""

    def advance_invalid(
        self, token: str | None = None, resolved: Optional[str] = None
    ) -> None:
        """Advance the scheduler for an invalid/unknown player command."""

        raw_token = "" if token is None else str(token)

        def _noop_action() -> tuple[str, Optional[str]]:
            return raw_token, resolved

        self.tick(_noop_action)

    def tick(self, player_action: Callable[[], Any]) -> None:
        """Advance the shared tick counter and resolve a full turn."""

        tick_id = random_pool.advance_rng_tick(self._rng_name)
        self._log_tick(tick_id)

        rng = random_pool.get_rng(self._rng_name)
        restore_token = self._inject_rng(rng)

        try:
            result = player_action()
            token, resolved = self._normalize_result(result)
            self._run_monster_turns(token, resolved)
            self._run_status_tick()
            self._run_free_actions(rng)
            self._run_monster_spawner()
        finally:
            self._restore_rng(restore_token)
            # Dev-only guardrails
            try:
                from mutants.bootstrap.lazyinit import ensure_player_state
                from mutants.services import player_state as pstate

                p = ensure_player_state(self._ctx)
                # (1) No persisted active snapshot allowed
                if isinstance(p, MutableMapping) and "active" in p:
                    LOG.error("player_state contains forbidden 'active' snapshot; stripping")
                    del p["active"]
                # (2) Drift check: any lingering view must match canonical
                y, x, z = pstate.canonical_player_pos(p)
                view = self._ctx.get("_active_view", {}).get("pos") if isinstance(self._ctx, Mapping) else None
                if view and list(view)[:3] != [y, x, z]:
                    LOG.warning("pos drift (view vs canonical): %s != %s", view, [y, x, z])
            except Exception:
                LOG.exception("post-turn guardrails failed")
            # NEW: end-of-command checkpoint — flush dirty caches back to store.
            try:
                ctx = self._ctx
                monsters = None
                if isinstance(ctx, Mapping):
                    monsters = ctx.get("monsters")
                else:
                    try:
                        monsters = getattr(ctx, "monsters", None)
                    except Exception:
                        monsters = None
                if monsters is not None and hasattr(monsters, "save"):
                    monsters.save()
            except Exception:  # pragma: no cover - defensive
                LOG.exception("Failed to flush caches at end of command")
            # End-of-command checkpoint: persist runtime player if dirty.
            try:
                from mutants.bootstrap.lazyinit import ensure_player_state
                from mutants.services import player_state as pstate

                player = ensure_player_state(self._ctx)
                if isinstance(player, dict) and player.get("_dirty"):
                    pstate.save_player_state(self._ctx)
                    player["_dirty"] = False
            except Exception:  # pragma: no cover
                LOG.exception("Failed to persist runtime player at end of command")

    # Internal helpers -------------------------------------------------
    def _normalize_result(self, result: Any) -> tuple[str, Optional[str]]:
        token = ""
        resolved: Optional[str] = None

        if isinstance(result, tuple):
            if result:
                raw_token = result[0]
                if raw_token is not None:
                    token = str(raw_token)
            if len(result) > 1:
                raw_resolved = result[1]
                if raw_resolved is not None:
                    resolved = str(raw_resolved)
        elif isinstance(result, Mapping):
            raw_token = result.get("token")
            raw_resolved = result.get("resolved")
            if raw_token is not None:
                token = str(raw_token)
            if raw_resolved is not None:
                resolved = str(raw_resolved)
        elif result is not None:
            token = str(result)

        return token, resolved

    def _inject_rng(self, rng: Any) -> tuple[str, object]:
        ctx = self._ctx
        if isinstance(ctx, MutableMapping):
            previous = ctx.get("monster_ai_rng", _MISSING)
            ctx["monster_ai_rng"] = rng
            return ("mapping", previous)
        try:
            previous = getattr(ctx, "monster_ai_rng", _MISSING)
            setattr(ctx, "monster_ai_rng", rng)
        except Exception:  # pragma: no cover - defensive
            return ("none", _MISSING)
        return ("attr", previous)

    def _restore_rng(self, token: tuple[str, object]) -> None:
        kind, previous = token
        ctx = self._ctx
        if kind == "mapping":
            mapping = ctx if isinstance(ctx, MutableMapping) else None
            if mapping is None:
                return
            if previous is _MISSING:
                mapping.pop("monster_ai_rng", None)
            else:
                mapping["monster_ai_rng"] = previous
        elif kind == "attr":
            if previous is _MISSING:
                try:
                    delattr(ctx, "monster_ai_rng")
                except Exception:  # pragma: no cover - defensive
                    pass
            else:
                try:
                    setattr(ctx, "monster_ai_rng", previous)
                except Exception:  # pragma: no cover - defensive
                    pass
        else:  # "none" or unknown token; nothing to restore.
            return

    def _inject_bonus_action(self, payload: Mapping[str, Any]) -> tuple[str, object]:
        ctx = self._ctx
        if isinstance(ctx, MutableMapping):
            previous = ctx.get("monster_ai_bonus_action", _MISSING)
            ctx["monster_ai_bonus_action"] = dict(payload)
            return ("mapping", previous)
        try:
            previous = getattr(ctx, "monster_ai_bonus_action", _MISSING)
            setattr(ctx, "monster_ai_bonus_action", dict(payload))
        except Exception:  # pragma: no cover - defensive
            return ("none", _MISSING)
        return ("attr", previous)

    def _restore_bonus_action(self, token: tuple[str, object]) -> None:
        kind, previous = token
        ctx = self._ctx
        if kind == "mapping":
            mapping = ctx if isinstance(ctx, MutableMapping) else None
            if mapping is None:
                return
            if previous is _MISSING:
                mapping.pop("monster_ai_bonus_action", None)
            else:
                mapping["monster_ai_bonus_action"] = previous
        elif kind == "attr":
            if previous is _MISSING:
                try:
                    delattr(ctx, "monster_ai_bonus_action")
                except Exception:  # pragma: no cover - defensive
                    pass
            else:
                try:
                    setattr(ctx, "monster_ai_bonus_action", previous)
                except Exception:  # pragma: no cover - defensive
                    pass
        else:
            return

    def _run_monster_turns(self, token: str, resolved: Optional[str]) -> None:
        try:
            from mutants.services import monster_ai

            monster_ai.on_player_command(self._ctx, token=token, resolved=resolved)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("Monster AI turn tick failed")

    def _run_status_tick(self) -> None:
        manager = self._status_manager
        if manager is None:
            return
        try:
            manager.tick()
        except Exception:  # pragma: no cover - defensive
            LOG.exception("Status manager tick failed")

    def _run_free_actions(self, rng: Any) -> None:
        if not self._free_actions:
            return
        pending = self._free_actions
        self._free_actions = []
        for action in pending:
            try:
                action(rng)
            except Exception:  # pragma: no cover - defensive
                LOG.exception("Free action dispatch failed")

    def _run_monster_spawner(self) -> None:
        ctx = self._ctx
        spawner = None
        if isinstance(ctx, Mapping):
            spawner = ctx.get("monster_spawner")
            if spawner is None:
                services = ctx.get("services")
                if isinstance(services, Mapping):
                    spawner = services.get("monster_spawner")
        elif ctx is not None:
            spawner = getattr(ctx, "monster_spawner", None)
        if spawner is None:
            return
        tick = getattr(spawner, "tick", None)
        if not callable(tick):
            return
        try:
            tick()
        except Exception:  # pragma: no cover - defensive
            LOG.exception("Monster spawner tick failed")

    def _log_tick(self, tick_id: int) -> None:
        message = f"tick={tick_id}"
        turnlog.emit(self._ctx, "TURN/TICK", message=message, tick=tick_id)
        LOG.info("TURN/TICK %s", message)

    # Public hooks -----------------------------------------------------
    def queue_free_emote(self, monster: Mapping[str, Any] | None, *, gate: str) -> None:
        """Schedule a free emote roll for *monster* after the current tick."""

        if monster is None:
            return

        def _action(rng: Any) -> None:
            from mutants.services.monster_ai import emote as emote_mod

            emote_mod.execute_free_emote(monster, self._ctx, rng, gate=gate)

        self._free_actions.append(_action)

    def _combat_config(self) -> CombatConfig | None:
        ctx = self._ctx
        if isinstance(ctx, Mapping):
            candidate = ctx.get("combat_config")
        else:
            candidate = getattr(ctx, "combat_config", None)
        if isinstance(candidate, CombatConfig):
            return candidate
        return None

    def queue_bonus_action(
        self,
        monster: Mapping[str, Any] | None,
        *,
        pickup_bias: float | None = None,
    ) -> None:
        """Schedule an immediate bonus cascade for *monster*.

        A random roll using ``pickup_bias`` may force the ``PICKUP`` gate when
        loot is available.  When *pickup_bias* is ``None`` the value from the
        active :class:`~mutants.services.combat_config.CombatConfig` is used,
        falling back to ``25%`` when no config is present.
        """

        if not isinstance(monster, Mapping):
            return

        monster_id = self._monster_id(monster)
        if not monster_id:
            monster_id = "?"

        if pickup_bias is None:
            config = self._combat_config()
            pct = 25
            if config is not None:
                pct = int(config.post_kill_force_pickup_pct)
            pickup_bias = pct / 100.0

        clamped_bias = max(0.0, min(1.0, float(pickup_bias)))
        cutoff = int(round(clamped_bias * 100))

        def _action(rng: Any) -> None:
            local_rng = rng
            roll: int
            try:
                if hasattr(local_rng, "randrange"):
                    roll = int(local_rng.randrange(100))
                else:
                    raise AttributeError
            except Exception:
                roll = int(random.randrange(100))
            force_pickup = roll < cutoff
            payload = {
                "monster_id": monster_id,
                "force_pickup": force_pickup,
                "bonus": True,
            }
            token = self._inject_bonus_action(payload)
            try:
                from mutants.services import monster_actions

                monster_actions.execute_random_action(monster, self._ctx, rng=rng)
            except Exception:  # pragma: no cover - defensive
                LOG.exception("Bonus monster action failed")
            finally:
                self._restore_bonus_action(token)

        self._free_actions.append(_action)

    def queue_player_respawn(
        self,
        player_id: str | None,
        killer_monster: Mapping[str, Any] | None,
        *,
        state: MutableMapping[str, Any] | None = None,
        active: MutableMapping[str, Any] | None = None,
        respawn_pos: Sequence[Any] | None = None,
    ) -> None:
        """Schedule the player-death handler to run after the current tick."""

        if killer_monster is None and state is None and active is None and player_id is None:
            return

        def _action(rng: Any) -> None:
            from mutants.services import player_death as _player_death

            _player_death.handle_player_death(
                player_id,
                killer_monster,
                state=state,
                active=active,
                respawn_pos=respawn_pos,
            )

        self._free_actions.append(_action)
