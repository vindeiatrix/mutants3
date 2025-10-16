from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, Iterable, Mapping, Optional

from mutants.services import player_state as pstate

LOG = logging.getLogger(__name__)
LOG_P = logging.getLogger("mutants.playersdbg")


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hp_snapshot() -> Optional[tuple[int, int]]:
    try:
        state = pstate.load_state()
    except Exception:  # pragma: no cover - defensive guard
        return None
    try:
        block = pstate.get_hp_for_active(state)
    except Exception:  # pragma: no cover - defensive guard
        return None
    if not isinstance(block, Mapping):
        return None
    current = _coerce_int(block.get("current"), 0)
    maximum = _coerce_int(block.get("max"), current)
    return current, maximum


def _observer_from_ctx(ctx: Any) -> "TurnObserver | None":
    if isinstance(ctx, Mapping):
        observer = ctx.get("turn_observer")
    else:
        observer = getattr(ctx, "turn_observer", None)
    return observer if isinstance(observer, TurnObserver) else None


def _sink_from_ctx(ctx: Any) -> Any:
    if isinstance(ctx, Mapping):
        return ctx.get("logsink")
    return getattr(ctx, "logsink", None)


def _format_meta(meta: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(meta.keys()):
        value = meta[key]
        if value is None:
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            token = ",".join(str(item) for item in value)
        elif isinstance(value, bool):
            token = "true" if value else "false"
        else:
            token = str(value)
        if token:
            parts.append(f"{key}={token}")
    return " ".join(parts)


def emit(ctx: Any, kind: str, *, message: str | None = None, **meta: Any) -> None:
    """Emit a structured turn log event.

    The event is written to the logsink (if present) and recorded by the
    :class:`TurnObserver` for playersdbg summaries.
    """

    text = message if message is not None else _format_meta(meta)
    sink = _sink_from_ctx(ctx)
    if sink and hasattr(sink, "handle"):
        try:
            sink.handle({"ts": "", "kind": kind, "text": text})
        except Exception:  # pragma: no cover - defensive guard
            LOG.exception("Failed to write structured log", extra={"kind": kind, "text": text})

    observer = _observer_from_ctx(ctx)
    if observer:
        observer.record(kind, meta, text)


def get_observer(ctx: Any) -> "TurnObserver | None":
    return _observer_from_ctx(ctx)


def _summarize_events(events: Iterable[tuple[str, Mapping[str, Any]]]) -> list[str]:
    summary: list[str] = []
    for kind, meta in events:
        if kind == "COMBAT/STRIKE":
            target = meta.get("target_name") or meta.get("target") or "?"
            damage = _coerce_int(meta.get("damage"), 0)
            killed = bool(meta.get("killed"))
            piece = f"strike {target} dmg={damage}"
            remain = meta.get("remaining_hp")
            if remain is not None:
                piece += f" hp={remain}"
            if killed:
                piece += " kill"
            summary.append(piece)
        elif kind.startswith("AI/ACT/"):
            action = kind.split("/", 2)[-1].lower()
            monster = meta.get("monster") or meta.get("mon") or "?"
            piece = f"{monster} {action}"
            if "damage" in meta:
                piece += f" dmg={_coerce_int(meta.get('damage'), 0)}"
            if "hp_after" in meta:
                piece += f" hp={_coerce_int(meta.get('hp_after'), 0)}"
            if meta.get("killed"):
                piece += " kill"
            if action == "pickup" and meta.get("item_id"):
                piece += f" {meta.get('item_id')}"
            if action == "convert" and meta.get("ions") is not None:
                piece += f" ions=+{_coerce_int(meta.get('ions'), 0)}"
            summary.append(piece)
        elif kind == "COMBAT/KILL":
            victim = meta.get("victim") or "?"
            drops = meta.get("drops")
            piece = f"kill {victim}"
            if drops is not None:
                piece += f" drops={_coerce_int(drops, 0)}"
            source = meta.get("source")
            if source:
                piece += f" by={source}"
            summary.append(piece)
        elif kind == "ITEM/CRACK":
            owner = meta.get("owner") or "?"
            item = meta.get("item_name") or meta.get("item_id") or "item"
            piece = f"crack {owner} {item}"
            summary.append(piece)
        elif kind == "ITEM/CONVERT":
            owner = meta.get("owner") or "?"
            ions = meta.get("ions")
            piece = f"convert {owner}"
            if ions is not None:
                piece += f" ions=+{_coerce_int(ions, 0)}"
            item = meta.get("item_name") or meta.get("item_id")
            if item:
                piece += f" {item}"
            summary.append(piece)
        elif kind == "COMBAT/HEAL":
            actor = meta.get("actor") or "?"
            healed = _coerce_int(meta.get("hp_restored"), 0)
            ions = _coerce_int(meta.get("ions_spent"), 0)
            piece = f"heal {actor} hp=+{healed}"
            if ions:
                piece += f" ions=-{ions}"
            summary.append(piece)
    return summary


@dataclass
class TurnObserver:
    """Collect structured events and emit a playersdbg summary each turn."""

    _active: bool = False
    _token: str | None = None
    _resolved: str | None = None
    _hp_before: tuple[int, int] | None = None
    _events: list[tuple[str, Dict[str, Any]]] = field(default_factory=list)

    def begin_turn(self, ctx: Any, token: str, resolved: Optional[str]) -> None:
        if not pstate._pdbg_enabled():
            self.reset()
            return
        self._active = True
        self._token = token
        self._resolved = resolved
        self._hp_before = _hp_snapshot()
        self._events.clear()

    def record(self, kind: str, meta: Mapping[str, Any], text: str | None = None) -> None:
        if not self._active:
            return
        payload: Dict[str, Any] = {}
        for key, value in meta.items():
            payload[str(key)] = value
        if text and "text" not in payload:
            payload["text"] = text
        self._events.append((kind, payload))

    def finish_turn(self, ctx: Any, token: str, resolved: Optional[str]) -> None:
        if not self._active:
            self.reset()
            return
        hp_after = _hp_snapshot()
        delta: Optional[int] = None
        if self._hp_before and hp_after:
            delta = hp_after[0] - self._hp_before[0]
        elif hp_after:
            delta = hp_after[0]
        header_parts: list[str] = []
        cmd = self._resolved or resolved or token or "?"
        if self._token and self._token != cmd:
            header_parts.append(f"cmd={cmd} ({self._token})")
        else:
            header_parts.append(f"cmd={cmd}")
        if hp_after:
            current, maximum = hp_after
            if delta is not None:
                header_parts.append(f"HPΔ={delta:+d} ({current}/{maximum})")
            else:
                header_parts.append(f"HP={current}/{maximum}")
        event_parts = _summarize_events(self._events)
        summary = " | ".join(header_parts + event_parts) if (header_parts or event_parts) else "no events"
        try:
            pstate._pdbg_setup_file_logging()
        except Exception:  # pragma: no cover - defensive guard
            pass
        LOG_P.info("[playersdbg] TURN %s", summary)
        self.reset()

    def reset(self) -> None:
        self._active = False
        self._token = None
        self._resolved = None
        self._hp_before = None
        self._events.clear()


__all__ = ["TurnObserver", "emit", "get_observer"]
