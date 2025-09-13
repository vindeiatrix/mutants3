from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass
class ArgSpec:
    """
    Spec for argument-taking commands.
    - verb: command verb for usage text (e.g., "GET", "DROP")
    - arg_policy: "required" | "optional" | "forbidden" (we currently use "required" for GET/DROP)
    - messages: dict with templates: "usage", "invalid", "success"
      Templates may use {subject} (raw user arg) and {name} (resolved display name).
    - reason_messages: optional map from engine/service reason codes -> templates
    - success_kind/warn_kind: feedback kinds to push on success/warn
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
    Common runner for commands that take a single 'subject' argument.
    Behavior:
      1) Trim the raw arg.
      2) If arg is required and empty -> push usage (warn) and return.
      3) Call do_action(subject) -> expect {"ok": bool, "reason"?: str, "display_name"| "name"| "item_name"?: str}
      4) On failure: map reason -> message; else success -> push success with name if available.
    """

    bus = ctx["feedback_bus"]
    subject = (arg or "").strip()

    # 1) Usage on empty
    if spec.arg_policy == "required" and not subject:
        usage = (spec.messages or {}).get("usage") or f"Type {spec.verb.upper()} [subject]."
        bus.push(spec.warn_kind, usage)
        return

    # 2) Execute action (services are expected to be no-ops on failure)
    decision = do_action(subject)
    if not decision.get("ok"):
        r = decision.get("reason") or "invalid"
        # Prefer explicit reason template, else fallback invalid message, else generic
        msg = None
        if spec.reason_messages and r in spec.reason_messages:
            msg = _fmt(spec.reason_messages[r], subject=subject)
        if not msg:
            msg = _fmt((spec.messages or {}).get("invalid"), subject=subject)
        bus.push(spec.warn_kind, msg or "Nothing happens.")
        return

    # 3) Success — use best available display name
    name = (
        decision.get("display_name")
        or decision.get("name")
        or decision.get("item_name")
        or subject
    )
    success = _fmt((spec.messages or {}).get("success"), name=name) or f"{spec.verb.title()} {name}."
    bus.push(spec.success_kind, success)

