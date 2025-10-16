"""Utilities for formatting combat log text."""

from __future__ import annotations

from typing import Any, Mapping

from mutants.services.monster_entities import DEFAULT_INNATE_ATTACK_LINE


def _coerce_str(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        token = value.strip()
        if token:
            return token
    if value is None:
        return default
    token = str(value).strip()
    return token or default


def render_innate_attack_line(
    monster_name: str,
    attack_obj: Mapping[str, Any] | None,
    target_name: str | None = None,
) -> str:
    """Render a monster's innate attack line for logging."""

    template = ""
    if isinstance(attack_obj, Mapping):
        candidate = attack_obj.get("line")
        if isinstance(candidate, str) and candidate.strip():
            template = candidate.strip()
    if not template:
        template = DEFAULT_INNATE_ATTACK_LINE

    attack_name = ""
    if isinstance(attack_obj, Mapping):
        attack_name = _coerce_str(attack_obj.get("name"), default="innate attack")
    if not attack_name:
        attack_name = "innate attack"

    monster_token = _coerce_str(monster_name, default="Monster")
    target_token = _coerce_str(target_name, default="you") if target_name is not None else "you"

    rendered = template
    rendered = rendered.replace("{monster}", monster_token)
    rendered = rendered.replace("{attack}", attack_name)
    rendered = rendered.replace("{target}", target_token)
    return rendered
