"""Data models for monster templates and instances."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

DEFAULT_INNATE_ATTACK_LINE = "The {monster} uses {attack}!"


def _sanitize_line(value: Any) -> str:
    if isinstance(value, str):
        token = value.strip()
        if token:
            return token
    return ""


@dataclass(frozen=True)
class MonsterTemplate:
    """Immutable representation of a catalog monster template."""

    monster_id: str
    name: str
    level: int
    hp_max: int
    armour_class: int
    spawn_years: Sequence[int]
    spawnable: bool
    taunt: str
    stats: Mapping[str, Any]
    innate_attack: Mapping[str, Any]
    exp_bonus: Optional[int]
    ions_min: Optional[int]
    ions_max: Optional[int]
    riblets_min: Optional[int]
    riblets_max: Optional[int]
    spells: Sequence[str]
    starter_armour: Sequence[str]
    starter_items: Sequence[str]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    ai_overrides: Optional[Mapping[str, Any]] = None

    @property
    def innate_attack_line(self) -> str:
        """Return the template's innate attack line template."""

        if isinstance(self.innate_attack, Mapping):
            line = _sanitize_line(self.innate_attack.get("line"))
            if line:
                return line
        return DEFAULT_INNATE_ATTACK_LINE


@dataclass
class MonsterInstance:
    """Light-weight runtime monster instance."""

    instance_id: str
    monster_id: str
    name: str
    innate_attack: Mapping[str, Any]
    template: Optional[MonsterTemplate] = None

    @property
    def innate_attack_line(self) -> str:
        """Return the innate attack line template for the instance."""

        if isinstance(self.innate_attack, Mapping):
            line = _sanitize_line(self.innate_attack.get("line"))
            if line:
                return line
        if self.template is not None:
            return self.template.innate_attack_line
        return DEFAULT_INNATE_ATTACK_LINE


def _iter_override_payloads(source: Any) -> Iterable[Mapping[str, Any]]:
    if source is None:
        return

    if isinstance(source, MonsterTemplate):
        yield from _iter_override_payloads(source.metadata)
        yield from _iter_override_payloads(source.ai_overrides)
        return

    if isinstance(source, Mapping):
        matched = False
        for key in ("monster_ai_overrides", "ai_overrides", "monster_ai"):
            payload = source.get(key)
            if isinstance(payload, Mapping):
                matched = True
                yield payload
        if not matched and any(
            key in source for key in ("prefers_ranged", "cascade", "cascade_modifiers", "tags", "species_tags")
        ):
            yield source
        metadata = source.get("metadata")
        if isinstance(metadata, Mapping):
            yield from _iter_override_payloads(metadata)
        return

    metadata = getattr(source, "metadata", None)
    if isinstance(metadata, Mapping):
        yield from _iter_override_payloads(metadata)
    overrides = getattr(source, "ai_overrides", None)
    if isinstance(overrides, Mapping):
        yield overrides


def _sanitize_ai_overrides(raw: Mapping[str, Any]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}

    if "prefers_ranged" in raw:
        overrides["prefers_ranged"] = bool(raw.get("prefers_ranged"))

    cascade_raw = raw.get("cascade") or raw.get("cascade_modifiers")
    if isinstance(cascade_raw, Mapping):
        cascade: dict[str, Any] = {}
        for key, value in cascade_raw.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, Mapping):
                cascade[key] = dict(value)
            else:
                cascade[key] = value
        if cascade:
            overrides["cascade"] = cascade

    tags_raw = raw.get("tags") or raw.get("species_tags")
    if isinstance(tags_raw, Sequence) and not isinstance(tags_raw, (str, bytes)):
        tags: list[str] = []
        for tag in tags_raw:
            token = str(tag).strip()
            if token and token not in tags:
                tags.append(token)
        if tags:
            overrides["tags"] = tuple(tags)

    return overrides


def resolve_monster_ai_overrides(*sources: Any) -> dict[str, Any]:
    """Return merged monster AI overrides from catalog metadata."""

    prefer: Optional[bool] = None
    cascade: dict[str, Any] = {}
    tags: list[str] = []

    for source in sources:
        if source is None:
            continue
        for payload in _iter_override_payloads(source):
            sanitized = _sanitize_ai_overrides(payload)
            if "prefers_ranged" in sanitized and prefer is None:
                prefer = bool(sanitized["prefers_ranged"])
            if "cascade" in sanitized:
                for key, value in sanitized["cascade"].items():
                    cascade.setdefault(key, value)
            if "tags" in sanitized:
                for tag in sanitized["tags"]:
                    if tag not in tags:
                        tags.append(tag)

    overrides: dict[str, Any] = {}
    if prefer is not None:
        overrides["prefers_ranged"] = prefer
    if cascade:
        overrides["cascade"] = cascade
    if tags:
        overrides["tags"] = tuple(tags)

    return overrides


def copy_innate_attack(
    source: Mapping[str, Any] | None, fallback_name: str = "Monster"
) -> dict[str, Any]:
    """Return a normalised copy of an innate attack mapping."""

    attack: dict[str, Any] = {}
    if isinstance(source, Mapping):
        attack.update({k: v for k, v in source.items() if isinstance(k, str)})

    attack_name = attack.get("name")
    if isinstance(attack_name, str):
        attack_name = attack_name.strip() or fallback_name
    else:
        attack_name = fallback_name
    attack["name"] = attack_name

    def _coerce_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    attack["power_base"] = _coerce_int(attack.get("power_base"))
    attack["power_per_level"] = _coerce_int(attack.get("power_per_level"))

    line_value = _sanitize_line(attack.get("line"))
    attack["line"] = line_value or DEFAULT_INNATE_ATTACK_LINE

    return attack


__all__ = [
    "DEFAULT_INNATE_ATTACK_LINE",
    "MonsterInstance",
    "MonsterTemplate",
    "copy_innate_attack",
    "resolve_monster_ai_overrides",
]
