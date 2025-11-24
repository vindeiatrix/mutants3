"""Ground item naming helpers (canonicalization, articles, duplicates)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Tuple

from ..registries import items_catalog, items_instances as itemsreg
from ..state import state_path

CATALOG_PATH = state_path("items", "catalog.json")
OVERRIDES_PATH = state_path("items", "naming_overrides.json")

_CAT_CACHE: Dict[str, Dict] = {}
_OVR_CACHE: Dict[str, str] = {}

_WEAPON_WEAR_TIERS: List[Tuple[int, str]] = [
    (80, "Only faint scuffs mar its surface; it's still battle-ready."),
    (60, "Nicks along the edge speak to frequent clashes."),
    (40, "Dents and chips have dulled its threat."),
    (20, "Splits run along its frame; it barely holds together."),
    (1, "It's moments from breaking apart entirely."),
]

_ARMOUR_WEAR_TIERS: List[Tuple[int, str]] = [
    (80, "Light scratches trace the armour's finish."),
    (60, "Dings and bent plates show hard campaigning."),
    (40, "Seams gape and padding is badly worn."),
    (20, "Cracks crawl across the armour; protection is waning."),
    (1, "It's nearly useless, more burden than bulwark."),
]


def _coerce_enchant_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, level))


def _coerce_condition(value: Any) -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return 100
    return max(0, min(100, amount))


def _catalog_description(template: Dict[str, Any]) -> str:
    if isinstance(template, dict):
        desc = template.get("description")
        if isinstance(desc, str) and desc:
            return desc
    return "You examine it."


def _resolve_template(inst: Dict[str, Any], catalog: Any) -> Dict[str, Any]:
    if not catalog:
        return {}
    tpl_id: str = ""
    if inst:
        for key in ("item_id", "catalog_id", "id"):
            candidate = inst.get(key)
            if candidate is None:
                continue
            tpl_id = str(candidate)
            if tpl_id:
                break
    if not tpl_id and inst:
        tpl_id = str(inst.get("iid") or inst.get("instance_id") or "")
    if not tpl_id:
        return {}
    template = catalog.get(tpl_id)
    return template if isinstance(template, dict) else {}


_SKULL_TEMPLATE = (
    "A shiver is sent down your spine as you realize this is the skull\n"
    "of a victim that has lost in a bloody battle. Looking closer, you realize\n"
    "this is the skull of a {article} {monster}!"
)


def _skull_monster_label(inst: Mapping[str, Any]) -> str:
    if not isinstance(inst, Mapping):
        return ""

    for key in ("skull_monster_name", "monster_name"):
        candidate = inst.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    for key in ("skull_monster_id", "monster_id"):
        candidate = inst.get(key)
        if candidate is None:
            continue
        token = str(candidate).strip()
        if token:
            return token.replace("_", " ").title()

    return ""


def _describe_skull(inst: Mapping[str, Any], fallback: str) -> str:
    monster_label = _skull_monster_label(inst)
    if not monster_label:
        return fallback

    article = _indefinite_article_lower(monster_label)
    return _SKULL_TEMPLATE.format(article=article, monster=monster_label)


def describe_instance(iid: str) -> str:
    """Return a narrative description for an item instance."""

    inst = itemsreg.get_instance(iid) or {}
    try:
        catalog = items_catalog.load_catalog()
    except (FileNotFoundError, ValueError):
        catalog = None
    template = _resolve_template(inst, catalog)
    base_description = _catalog_description(template)

    if not inst:
        return base_description

    item_id = str(inst.get("item_id") or inst.get("catalog_id") or inst.get("id") or "")
    if item_id == "skull":
        return _describe_skull(inst, base_description)
    if item_id in {itemsreg.BROKEN_WEAPON_ID, itemsreg.BROKEN_ARMOUR_ID}:
        return base_description

    enchant_level = _coerce_enchant_level(inst.get("enchant_level"))
    if enchant_level >= 1:
        return f"{base_description} It bears a +{enchant_level} enchantment."

    condition = _coerce_condition(inst.get("condition"))
    if condition >= 100 or condition == 0:
        return base_description

    tiers = _ARMOUR_WEAR_TIERS if bool(template.get("armour")) else _WEAPON_WEAR_TIERS
    for threshold, line in tiers:
        if condition >= threshold:
            return line
    return tiers[-1][1]


def _load_catalog() -> Dict[str, Dict]:
    global _CAT_CACHE
    if _CAT_CACHE:
        return _CAT_CACHE
    try:
        data = json.load(CATALOG_PATH.open("r", encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    _CAT_CACHE = data.get("items", data) if isinstance(data, dict) else {}
    return _CAT_CACHE


def _load_overrides() -> Dict[str, str]:
    global _OVR_CACHE
    if _OVR_CACHE:
        return _OVR_CACHE
    try:
        _OVR_CACHE = json.load(OVERRIDES_PATH.open("r", encoding="utf-8"))
    except FileNotFoundError:
        _OVR_CACHE = {}
    return _OVR_CACHE


def canonical_name(item_id: str) -> str:
    """Return display name for *item_id* using catalog/overrides or derive."""
    cat = _load_catalog()
    ovr = _load_overrides()
    iid = str(item_id)
    if iid in ovr and isinstance(ovr[iid], str) and ovr[iid].strip():
        return ovr[iid].strip()
    meta = cat.get(iid) if isinstance(cat, dict) else None
    if isinstance(meta, dict):
        for k in ("display_name", "name", "title"):
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    base = iid.replace("_", "-")
    parts = [p.capitalize() if p else p for p in base.split("-")]
    return "-".join(parts)


_VOWEL_RE = re.compile(r"[aeiou]", re.IGNORECASE)


def _indefinite_article_lower(name: str) -> str:
    first_alpha = next((ch for ch in name if ch.isalpha()), "")
    if first_alpha and _VOWEL_RE.match(first_alpha):
        return "an"
    return "a"


def with_article(name: str) -> str:
    """Prefix with A/An based on first alphabetic character."""
    first_alpha = next((ch for ch in name if ch.isalpha()), "")
    if first_alpha and _VOWEL_RE.match(first_alpha):
        return f"An {name}"
    return f"A {name}"


def number_duplicates(names: List[str]) -> List[str]:
    """Append " (n)" to duplicates starting from second occurrence."""
    seen: Dict[str, int] = {}
    out: List[str] = []
    for n in names:
        count = seen.get(n, 0)
        if count == 0:
            out.append(n)
        else:
            out.append(f"{n} ({count})")
        seen[n] = count + 1
    return out


def render_ground_list(item_ids: List[str]) -> str:
    """Return comma-separated ground line with articles and numbering."""
    base = [canonical_name(i) for i in item_ids]
    numbered = number_duplicates(base)
    with_articles = [with_article(n) for n in numbered]
    return ", ".join(with_articles) + "."


def item_label(inst, tpl, *, show_charges: bool = False) -> str:
    """Return the display name for an item instance."""
    # Fallback chain for item identifier
    item_id = tpl.get("item_id") or inst.get("item_id")

    # Detect if item_id has degenerated to the instance ID (GUID)
    iid = inst.get("iid") or inst.get("instance_id")
    if str(item_id) == str(iid) and tpl.get("name"):
        # If so, prefer the template name if available
        base = tpl.get("name")
    else:
        # Otherwise, canonicalize the item_id as usual
        base = canonical_name(str(item_id)) if item_id else tpl.get("name") or "Item"

    if show_charges and (tpl.get("uses_charges") or tpl.get("charges_max") is not None):
        ch = inst.get("charges")
        if ch is not None:
            return f"{base} ({int(ch)})"
    return base


def canonical_name_from_iid(iid: str, *, show_charges: bool = False) -> str:
    """Resolve display name for an instance-id via the items registry."""
    try:
        from ..registries import items_instances as itemsreg, items_catalog
        inst = itemsreg.get_instance(iid) or {}
        cat = items_catalog.load_catalog()
        tpl = {}
        if inst:
            tpl = cat.get(inst.get("item_id")) or {}
        return item_label(inst, tpl, show_charges=show_charges)
    except Exception:
        return iid

