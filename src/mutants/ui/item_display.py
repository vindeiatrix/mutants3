"""Ground item naming helpers (canonicalization, articles, duplicates)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = ROOT / "state" / "items" / "catalog.json"
OVERRIDES_PATH = ROOT / "state" / "items" / "naming_overrides.json"

_CAT_CACHE: Dict[str, Dict] = {}
_OVR_CACHE: Dict[str, str] = {}


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
    """Return the display name for an item instance.

    Charges are shown only when ``show_charges`` is ``True``.
    """
    item_id = tpl.get("item_id") or inst.get("item_id")
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

