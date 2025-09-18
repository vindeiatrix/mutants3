from __future__ import annotations

import logging
import os
import sys
from typing import Any, List, Tuple

LOG = logging.getLogger("mutants.itemsdbg")


def enabled() -> bool:
    return bool(os.environ.get("ITEMS_DEBUG"))


def setup_file_logging() -> None:
    """Write probes to state/logs/items_debug.log."""

    if not enabled():
        return
    if any(
        getattr(handler, "baseFilename", "").endswith("items_debug.log")
        for handler in LOG.handlers
        if hasattr(handler, "baseFilename")
    ):
        return
    os.makedirs("state/logs", exist_ok=True)
    fh = logging.FileHandler("state/logs/items_debug.log", encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fmt)
    LOG.setLevel(logging.INFO)
    LOG.addHandler(fh)
    # also echo to console for quick eyeballing
    if not any(isinstance(handler, logging.StreamHandler) for handler in LOG.handlers):
        LOG.addHandler(logging.StreamHandler())


def _mod_identity(mod: Any) -> str:
    try:
        module = sys.modules.get(mod.__name__, mod)
        return (
            f"{getattr(mod, '__name__', '?')} "
            f"file={getattr(mod, '__file__', '?')} "
            f"mod_id={id(module)}"
        )
    except Exception:
        return f"{getattr(mod, '__name__', '?')}"


def _tile_items(itemsreg: Any, year: int, x: int, y: int) -> Tuple[List[str], List[str], int]:
    """
    Return ([item_ids], [instance_ids], cache_obj_id).

    Tries to use the module's cache if available to mirror command behavior.
    """

    cache_obj_id = -1
    raw = None
    try:
        if hasattr(itemsreg, "_cache"):
            raw = itemsreg._cache()  # type: ignore[attr-defined]
            cache_obj_id = id(raw)
    except Exception:
        raw = None
    if raw is None:
        try:
            raw = itemsreg.list_instances_at(year, x, y)
        except Exception:
            raw = []
    item_ids: List[str] = []
    inst_ids: List[str] = []
    tgt = (int(year), int(x), int(y))
    # Fallback if raw is the global list
    if raw and isinstance(raw, list) and raw and isinstance(raw[0], dict) and "pos" in raw[0]:
        seq = raw
    else:
        # last resort: call list_instances_at which filters at source
        try:
            seq = itemsreg.list_instances_at(year, x, y)
        except Exception:
            seq = []
    for inst in seq:
        pos = inst.get("pos") or {}
        p = (
            int(pos.get("year", inst.get("year", -1))),
            int(pos.get("x", inst.get("x", 99999))),
            int(pos.get("y", inst.get("y", 99999))),
        )
        if p == tgt:
            item_ids.append(
                str(
                    inst.get("item_id")
                    or inst.get("catalog_id")
                    or inst.get("id")
                )
            )
            inst_ids.append(str(inst.get("iid") or inst.get("instance_id")))
    return item_ids, inst_ids, cache_obj_id


def probe(tag: str, itemsreg: Any, year: int, x: int, y: int) -> None:
    """Log a compact, comparable snapshot for renderer/command paths."""

    if not enabled():
        return
    setup_file_logging()
    item_ids, inst_ids, cache_id = _tile_items(itemsreg, year, x, y)
    LOG.info(
        "[itemsdbg] %s year=%s x=%s y=%s items=%s insts=%s mod={%s} cache_id=%s",
        tag,
        year,
        x,
        y,
        item_ids,
        inst_ids,
        _mod_identity(itemsreg),
        cache_id,
    )

