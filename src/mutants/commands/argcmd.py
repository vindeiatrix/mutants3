from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
import shlex

from mutants.util.directions import resolve_dir


# ---------- Single-argument runner ----------

@dataclass
class ArgSpec:
    """
    Spec for single-argument commands.
    - verb: command verb for usage text (e.g., "GET", "DROP")
    - arg_policy: "required" | "optional" | "forbidden"
    - messages: dict with templates: "usage", "invalid", "success"
      Templates may use {subject} (raw user arg) and {name} (resolved display name).
    - reason_messages: optional map reason-code -> template
    - success_kind/warn_kind: feedback kinds on success/warn
    """
    verb: str
    arg_policy: str = "required"
    messages: Optional[Dict[str, str]] = None
    reason_messages: Optional[Dict[str, str]] = None
    success_kind: str = "SYSTEM/OK"
    warn_kind: str = "SYSTEM/WARN"


def _fmt(tmpl: Optional[str], **kw: Any) -> Optional[str]:
    return tmpl.format(**kw) if tmpl else None


def run_argcmd(
    ctx: Dict[str, Any],
    spec: ArgSpec,
    arg: str,
    do_action: Callable[[str], Dict[str, Any]],
) -> None:
    """
    Single-arg runner.
    1) Trim arg.
    2) If required & empty -> usage.
    3) do_action(subject) -> {"ok": bool, "reason"?: str, "display_name"|"name"|"item_name"?: str}
    4) On failure: map reason; on success: push success with best-available name.
    """
    bus = ctx["feedback_bus"]
    subject = (arg or "").strip()

    if spec.arg_policy == "required" and not subject:
        usage = (spec.messages or {}).get("usage") or f"Type {spec.verb.upper()} [subject]."
        bus.push(spec.warn_kind, usage)
        return

    decision = do_action(subject)
    if not decision.get("ok"):
        r = decision.get("reason") or "invalid"
        msg = None
        fmt_vals = dict(decision)
        fmt_vals["subject"] = subject
        cands = fmt_vals.get("candidates")
        if isinstance(cands, list):
            fmt_vals["candidates"] = ", ".join(cands)
        if spec.reason_messages and r in spec.reason_messages:
            msg = _fmt(spec.reason_messages[r], **fmt_vals)
        if not msg and decision.get("message"):
            msg = str(decision["message"])
        if not msg:
            msg = _fmt((spec.messages or {}).get("invalid"), subject=subject)
        bus.push(spec.warn_kind, msg or "Nothing happens.")
        return

    name = decision.get("display_name") or decision.get("name") or decision.get("item_name") or subject
    success = _fmt((spec.messages or {}).get("success"), name=name) or f"{spec.verb.title()} {name}."
    bus.push(spec.success_kind, success)


# ---------- Two-argument (positional) runner ----------

@dataclass
class PosArg:
    name: str                 # e.g., "dir", "item", "amt"
    kind: str                 # "direction" | "item_in_inventory" | "literal:ions" | "int_range:100000:999999"
    required: bool = True


@dataclass
class PosArgSpec:
    verb: str
    args: List[PosArg]
    messages: Optional[Dict[str, str]] = None  # "usage", "invalid", "success"
    reason_messages: Optional[Dict[str, str]] = None  # reason -> template
    success_kind: str = "SYSTEM/OK"
    warn_kind: str = "SYSTEM/WARN"


def _tokenize(s: str) -> List[str]:
    # Supports quotes for multi-word names; preserves hyphens.
    return shlex.split(s or "")


def coerce_direction(tok: str) -> Optional[str]:
    return resolve_dir(tok)


def _parse_int_range(tok: str, lo: int, hi: int) -> Optional[int]:
    try:
        v = int(tok.replace("_", ""))
    except Exception:
        return None
    if lo <= v <= hi:
        return v
    return None


def _check_literal(tok: str, lit: str) -> bool:
    return tok.lower() == lit.lower()


def _parse_by_kind(tok: str, kind: str) -> Tuple[Optional[Any], Optional[str]]:
    """
    Returns (value, reason_if_invalid).
    Only kinds needed for POINT/THROW/BUY-ions are implemented.
    """
    if kind == "direction":
        v = coerce_direction(tok)
        return (v, None if v else "invalid_direction")
    if kind == "item_in_inventory":
        # Parsing is pass-through; actual resolution happens in the action/service.
        # Armor is excluded by services; runner just carries the token through.
        return ((tok or "").strip() or None, "not_carrying" if not tok else None)
    if kind.startswith("literal:"):
        expect = kind.split(":", 1)[1]
        return (tok, None) if _check_literal(tok, expect) else (None, "wrong_item_literal")
    if kind.startswith("int_range:"):
        _, lo, hi = kind.split(":")
        v = _parse_int_range(tok, int(lo), int(hi))
        return (v, None) if v is not None else (None, "invalid_amount_range")
    # Fallback: unknown kind treated as invalid
    return (None, "invalid_argument")


def run_argcmd_positional(
    ctx: Dict[str, Any],
    spec: PosArgSpec,
    arg: str,
    do_action: Callable[..., Dict[str, Any]],
) -> None:
    """
    Two-arg (positional) runner.
    - Tokenizes input (supports quotes).
    - Enforces required argument count -> usage.
    - Validates each arg by `kind`; first parse error -> mapped warn and return.
    - On success, calls do_action(**values) with names from spec.args (e.g., dir, item, amt).
    - Decision contract: {"ok": bool, "reason"?: str, ...} (as in single-arg).
    """
    bus = ctx["feedback_bus"]
    toks = _tokenize(arg)
    # Check presence counts
    required = sum(1 for a in spec.args if a.required)
    if len(toks) < required:
        usage = (spec.messages or {}).get("usage") or f"Type {spec.verb.upper()} [args]."
        bus.push(spec.warn_kind, usage)
        return

    values: Dict[str, Any] = {}
    for idx, a in enumerate(spec.args):
        tok = toks[idx] if idx < len(toks) else ""
        if not tok and a.required:
            usage = (spec.messages or {}).get("usage") or f"Type {spec.verb.upper()} [args]."
            bus.push(spec.warn_kind, usage)
            return
        if not tok and not a.required:
            continue
        v, reason = _parse_by_kind(tok, a.kind)
        if reason:
            # Map reason -> message, else generic invalid
            msg = None
            if spec.reason_messages and reason in spec.reason_messages:
                # allow templates like "We don't have {what} in stock." etc.
                msg = _fmt(
                    spec.reason_messages[reason], **{a.name: tok, "item": tok}
                )
            if not msg:
                msg = _fmt(
                    (spec.messages or {}).get("invalid"),
                    **{a.name: tok, "item": tok},
                )
            bus.push(spec.warn_kind, msg or "Nothing happens.")
            return
        values[a.name] = v if v is not None else tok

    decision = do_action(**values)
    if not decision.get("ok"):
        r = decision.get("reason") or "invalid"
        msg = None
        fmt_vals = dict(values)
        fmt_vals.setdefault("item", values.get("item"))
        if spec.reason_messages and r in spec.reason_messages:
            msg = _fmt(spec.reason_messages[r], **fmt_vals)
        if not msg and decision.get("message"):
            msg = str(decision["message"])
        if not msg:
            msg = _fmt((spec.messages or {}).get("invalid"), **fmt_vals)
        bus.push(spec.warn_kind, msg or "Nothing happens.")
        return

    fmt_vals = dict(values)
    fmt_vals.setdefault("item", values.get("item"))
    name = (
        decision.get("display_name")
        or decision.get("name")
        or decision.get("item_name")
    )
    if name:
        fmt_vals.setdefault("name", name)

    success = _fmt((spec.messages or {}).get("success"), **fmt_vals) or f"{spec.verb.title()} OK."
    bus.push(spec.success_kind, success)

