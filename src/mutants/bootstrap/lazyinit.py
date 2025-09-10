# src/mutants/bootstrap/lazyinit.py
"""
Lazy init for player live state.

Behavior:
- If state/playerlivestate.json exists and is valid, load and return it.
- If missing or invalid, read class templates, instantiate the 5 classes with
  derived fields, atomically write state/playerlivestate.json, then return it.

Notes:
- Templates are expected at package data: mutants/data/startingclasstemplates.json
  (or pass a filesystem fallback path to ensure_player_state).
- Starting Armour Class is computed from DEX-only (fill in your real formula).
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from importlib.resources import files  # Python 3.9+
except ImportError:  # pragma: no cover
    import importlib_resources  # type: ignore
    files = importlib_resources.files  # type: ignore


# ---------- Domain helpers ----------

def compute_ac_from_dex(dex: int) -> int:
    """TODO: Replace with your actual DEX → AC rule. Placeholder uses DEX directly."""
    return int(dex)


# ---------- IO helpers ----------

def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_templates(pkg: str = "mutants.data",
                   resource_name: str = "startingclasstemplates.json",
                   fs_fallback: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Load starting class templates from package data; fall back to a filesystem path if provided.
    """
    try:
        text = (files(pkg) / resource_name).read_text(encoding="utf-8")  # type: ignore[arg-type]
        return json.loads(text)
    except Exception:
        if fs_fallback and fs_fallback.exists():
            return json.loads(fs_fallback.read_text(encoding="utf-8"))
        raise


# ---------- Construction ----------

def make_player_from_template(t: Dict[str, Any], make_active: bool = False) -> Dict[str, Any]:
    cls = t["class"]
    stats = t.get("base_stats", {})
    dex = int(stats.get("dex", 0))
    hp_max = int(t.get("hp_max_start", 0))

    # Normalize inventory_start entries to objects with item_id/qty
    inv_raw = t.get("inventory_start", [])
    inventory: List[Dict[str, Any]] = []
    for it in inv_raw:
        if isinstance(it, str):
            inventory.append({"item_id": it, "qty": 1})
        elif isinstance(it, dict):
            inventory.append({"item_id": it.get("item_id"), "qty": int(it.get("qty", 1))})

    entry = {
        "id": f"player_{cls.lower()}",
        "name": cls,                     # default to class name; can be renamed later
        "class": cls,
        "is_active": bool(make_active),
        "pos": t.get("start_pos", [2000, 0, 0]),

        "stats": {
            "str": int(stats.get("str", 0)),
            "int": int(stats.get("int", 0)),
            "wis": int(stats.get("wis", 0)),
            "dex": dex,
            "con": int(stats.get("con", 0)),
            "cha": int(stats.get("cha", 0)),
        },

        "hp": {"current": hp_max, "max": hp_max},
        "exhaustion": int(t.get("exhaustion_start", 0)),
        "exp_points": int(t.get("exp_start", 0)),
        "level": int(t.get("level_start", 1)),
        "riblets": int(t.get("riblets_start", 0)),
        "ions": int(t.get("ions_start", 0)),

        "armour": {
            "wearing": t.get("armour_start", None),
            "armour_class": compute_ac_from_dex(dex),  # DEX-only at start
        },
        "readied_spell": t.get("readied_spell_start", None),
        "target_monster_id": None,

        "inventory": inventory,
        "carried_weight": 0,

        "conditions": {
            "poisoned": False,
            "encumbered": False,
            "ion_starving": False
        },
        "notes": t.get("notes", "")
    }
    return entry


# ---------- Public API ----------

def ensure_player_state(state_dir: str = "state",
                        out_name: str = "playerlivestate.json",
                        templates_pkg: str = "mutants.data",
                        templates_resource: str = "startingclasstemplates.json",
                        fs_fallback: Optional[str] = None,
                        active_first_class: str = "Thief") -> Dict[str, Any]:
    """
    Ensure playerlivestate.json exists; create from templates if missing.
    Returns a dict: {"schema_version": 1, "players": [...], "active_id": "..."}.
    """
    out_path = Path(state_dir) / out_name

    # Load if present and valid; otherwise rebuild.
    if out_path.exists():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
            if data.get("schema_version") != 1:
                raise ValueError(f"unexpected schema_version={data.get('schema_version')}")
            if "players" not in data or "active_id" not in data:
                raise ValueError("missing required keys: players/active_id")
            return data
        except Exception as e:
            print(f"[warn] {out_path} invalid or unreadable ({e}); rebuilding from templates...", flush=True)
            # Move the bad file aside so we don't overwrite it.
            try:
                bad_path = out_path.with_suffix(out_path.suffix + ".bad")
                os.replace(out_path, bad_path)
            except Exception:
                pass

    templates = load_templates(
        pkg=templates_pkg,
        resource_name=templates_resource,
        fs_fallback=Path(fs_fallback) if fs_fallback else None
    )

    # Build entries; mark exactly one active (match class, else first)
    players: List[Dict[str, Any]] = []
    active_id: Optional[str] = None
    for i, t in enumerate(templates):
        make_active = (t.get("class") == active_first_class) or (active_id is None and i == 0)
        p = make_player_from_template(t, make_active=make_active)
        if make_active:
            active_id = p["id"]
        players.append(p)

    state = {"schema_version": 1, "players": players, "active_id": active_id}
    atomic_write_json(out_path, state)
    return state


if __name__ == "__main__":
    st = ensure_player_state()
    print(f"playerlivestate.json ready with {len(st.get('players', []))} classes; active_id={st.get('active_id')}")
