from __future__ import annotations

from typing import Any, Mapping
import re

_NO_BREAK_HYPHEN = "\u2011"  # U+2011
_NBSP = "\u00A0"             # U+00A0

_ARTICLE_RE = re.compile(r"^(A|An) ")


# Canonical feedback template identifiers.
TEMPLATE_MONSTER_MELEE_HIT = "combat.monster.melee_hit"
TEMPLATE_MONSTER_RANGED_HIT = "combat.monster.ranged_hit"
TEMPLATE_MONSTER_CONVERT = "combat.monster.convert"
TEMPLATE_MONSTER_HEAL = "combat.monster.heal"
TEMPLATE_MONSTER_HEAL_VISUAL = "combat.monster.heal_visual"
TEMPLATE_MONSTER_DROP = "combat.monster.drop"

_TEMPLATE_FORMATS: dict[str, str] = {
    TEMPLATE_MONSTER_MELEE_HIT: "{monster} has hit you with his {weapon}!",
    TEMPLATE_MONSTER_RANGED_HIT: "{monster} has shot you with his {weapon}!",
    TEMPLATE_MONSTER_CONVERT: "{monster} converts loot worth {ions} ions.",
    TEMPLATE_MONSTER_HEAL: "{monster} restores {hp} HP ({ions} ions).",
    TEMPLATE_MONSTER_HEAL_VISUAL: "{monster}'s body is glowing!",
    TEMPLATE_MONSTER_DROP: "{monster} has dropped {item}.",
}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


class _TemplateArgs(dict[str, str]):
    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        return "{" + key + "}"


def harden_final_display(s: str) -> str:
    """Apply non-breaking rules to a final display string.

    - Replace ASCII '-' with U+2011 no-break hyphen.
    - Bind leading article (A/An) to next token with U+00A0.
    """
    if not s:
        return s
    s = s.replace("-", _NO_BREAK_HYPHEN)
    s = _ARTICLE_RE.sub(lambda m: f"{m.group(1)}{_NBSP}", s)
    return s


def render_feedback_template(template: str, **params: Any) -> str:
    """Render *template* using canonical formats and return the hardened text."""

    fmt = _TEMPLATE_FORMATS.get(template)
    if fmt is None:
        raise KeyError(f"Unknown feedback template: {template}")
    mapping = _TemplateArgs({key: _stringify(value) for key, value in params.items()})
    rendered = fmt.format_map(mapping)
    return harden_final_display(rendered)


def resolve_feedback_text(event: Mapping[str, Any] | None) -> str:
    """Return the canonical text for *event* applying templates when present."""

    if not isinstance(event, Mapping):
        return ""
    template_key = event.get("template")
    if isinstance(template_key, str) and template_key in _TEMPLATE_FORMATS:
        params = {
            key: value
            for key, value in event.items()
            if key not in {"template", "text", "ts", "kind"}
        }
        return render_feedback_template(template_key, **params)
    text = event.get("text")
    return harden_final_display(_stringify(text))


__all__ = [
    "TEMPLATE_MONSTER_MELEE_HIT",
    "TEMPLATE_MONSTER_RANGED_HIT",
    "TEMPLATE_MONSTER_CONVERT",
    "TEMPLATE_MONSTER_HEAL",
    "TEMPLATE_MONSTER_HEAL_VISUAL",
    "TEMPLATE_MONSTER_DROP",
    "harden_final_display",
    "render_feedback_template",
    "resolve_feedback_text",
]
