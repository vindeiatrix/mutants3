from __future__ import annotations

import json
from pathlib import Path

from mutants.ui import item_display as idisp
from mutants.ui import render_items as ritems
from mutants.ui.wrap import wrap_list


CATALOG_PATH = Path(__file__).resolve().parents[1] / "state" / "items" / "catalog.json"


def _load_catalog_ids() -> list[str]:
    data = json.load(CATALOG_PATH.open("r", encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("items", [])
    else:
        items = data
    ids: list[str] = []
    for meta in items:
        iid = meta.get("item_id") or meta.get("id")
        if iid:
            ids.append(str(iid))
    return ids


def _build_display_names(bases: list[str]) -> list[str]:
    out: list[str] = []
    for base in bases:
        duped = idisp.number_duplicates([base, base])
        with_articles = [idisp.with_article(n) for n in duped]
        hardened = [ritems.harden_display_nonbreak(s) for s in with_articles]
        out.extend(hardened)
    return out


def test_catalog_items_do_not_break():
    ids = _load_catalog_ids()
    bases = [idisp.canonical_name(iid) for iid in ids]
    display = _build_display_names(bases)
    wrapped = wrap_list(display, width=80)
    joined = "\n".join(wrapped)
    assert "-\n" not in joined
    assert "A \n" not in joined
    assert "An \n" not in joined


def test_fuzz_items_do_not_break():
    fuzz = [
        "Ion-Decay",
        "Exo-Plate",
        "Multi-Hyphen-Thing",
        "Mini-XL",
        "Rock-N-Roll",
        "Ultra-Super-Long-Concatenation-Token",
    ]
    display = _build_display_names(fuzz)
    wrapped = wrap_list(display, width=40)
    joined = "\n".join(wrapped)
    assert "-\n" not in joined
    assert "A \n" not in joined
    assert "An \n" not in joined

