"""Utility to repair duplicate item instance IDs across state files."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping

from mutants.io.atomic import atomic_write_json
from mutants.registries import items_instances


def _instance_id(inst: Mapping[str, Any]) -> str:
    for key in ("iid", "instance_id"):
        value = inst.get(key)
        if isinstance(value, str) and value:
            return value
        if value is not None:
            token = str(value).strip()
            if token:
                return token
    return ""


def _coerce_list(obj: Any) -> List[Any]:
    if isinstance(obj, list):
        return obj
    return []


def _coerce_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    return {}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _remint_instances(instances: List[MutableMapping[str, Any]]) -> tuple[Dict[str, List[str]], bool]:
    seen_ids: set[str] = set()
    groups: Dict[str, List[int]] = defaultdict(list)
    for idx, inst in enumerate(instances):
        current = _instance_id(inst)
        if current:
            groups[current].append(idx)
            seen_ids.add(current)

    replacements: Dict[str, List[str]] = {}
    changed = False

    for old_id, indices in groups.items():
        ordinals: List[str] = []
        for ordinal, idx in enumerate(sorted(indices)):
            inst = instances[idx]
            current = _instance_id(inst)
            if ordinal == 0 and current:
                new_id = current
            else:
                new_id = items_instances.mint_iid(seen=seen_ids)
                seen_ids.add(new_id)
                inst["iid"] = new_id
                inst["instance_id"] = new_id
                changed = True
            ordinals.append(new_id)
        replacements[old_id] = ordinals

    # Ensure instances missing ids receive one so downstream references remain valid.
    for inst in instances:
        current = _instance_id(inst)
        if current:
            continue
        new_id = items_instances.mint_iid(seen=seen_ids)
        seen_ids.add(new_id)
        inst["iid"] = new_id
        inst["instance_id"] = new_id
        changed = True

    return replacements, changed


class IIDAssigner:
    """Deterministic mapper from original iid to reminted iid values."""

    def __init__(self, replacements: Mapping[str, List[str]]):
        self._sequences: Dict[str, List[str]] = {}
        for old, seq in replacements.items():
            self._sequences[str(old)] = list(seq)
        self._assigned: Dict[str, List[str]] = defaultdict(list)

    def assign_next(self, old_id: str) -> str:
        token = str(old_id)
        if not token:
            return token
        sequence = self._sequences.get(token)
        if not sequence:
            return token
        idx = len(self._assigned[token])
        if idx < len(sequence):
            result = sequence[idx]
        else:
            result = sequence[-1]
        self._assigned[token].append(result)
        return result

    def reuse_for_sequence(self, old_id: str, occurrence: int) -> str:
        token = str(old_id)
        if not token:
            return token
        assigned = self._assigned.get(token)
        if assigned and occurrence < len(assigned):
            return assigned[occurrence]
        sequence = self._sequences.get(token)
        if sequence:
            if occurrence < len(sequence):
                return sequence[occurrence]
            return sequence[-1]
        return token

    def reuse_scalar(self, old_id: str) -> str:
        token = str(old_id)
        if not token:
            return token
        assigned = self._assigned.get(token)
        if assigned:
            return assigned[0]
        sequence = self._sequences.get(token)
        if sequence:
            return sequence[0]
        return token

    def reuse_latest(self, old_id: str) -> str:
        token = str(old_id)
        if not token:
            return token
        assigned = self._assigned.get(token)
        if assigned:
            return assigned[-1]
        sequence = self._sequences.get(token)
        if sequence:
            return sequence[-1]
        return token


def _remap_sequence(values: Iterable[Any], assigner: IIDAssigner, *, consume: bool) -> List[Any]:
    counters: Dict[str, int] = defaultdict(int)
    result: List[Any] = []
    for value in values:
        token = str(value).strip() if value is not None else ""
        if not token:
            result.append(value)
            continue
        if consume:
            new_id = assigner.assign_next(token)
        else:
            idx = counters[token]
            new_id = assigner.reuse_for_sequence(token, idx)
            counters[token] = idx + 1
        result.append(new_id)
    return result


def _remap_scalar(value: Any, assigner: IIDAssigner, *, latest: bool = False) -> Any:
    token = str(value).strip() if isinstance(value, str) or value is not None else ""
    if not token:
        return value
    return assigner.reuse_latest(token) if latest else assigner.reuse_scalar(token)


def _remap_player_payload(payload: MutableMapping[str, Any], assigner: IIDAssigner, *, canonical: bool) -> None:
    bags = _coerce_dict(payload.get("bags"))
    for name, seq in bags.items():
        if isinstance(seq, list):
            bags[name] = _remap_sequence(seq, assigner, consume=canonical)
    if bags:
        payload["bags"] = bags

    inventory = payload.get("inventory")
    if isinstance(inventory, list):
        payload["inventory"] = _remap_sequence(inventory, assigner, consume=False)

    equip_by_class = _coerce_dict(payload.get("equipment_by_class"))
    for cls, entry in equip_by_class.items():
        if isinstance(entry, dict):
            armour = entry.get("armour") or entry.get("armor")
            if isinstance(armour, dict):
                for key in ("wearing", "iid", "instance_id"):
                    if isinstance(armour.get(key), str):
                        armour[key] = _remap_scalar(armour[key], assigner)
            elif isinstance(armour, str):
                entry["armour"] = _remap_scalar(armour, assigner)
            weapon = entry.get("weapon")
            if isinstance(weapon, str):
                entry["weapon"] = _remap_scalar(weapon, assigner)
        elif isinstance(entry, str):
            equip_by_class[cls] = _remap_scalar(entry, assigner)
    if equip_by_class:
        payload["equipment_by_class"] = equip_by_class

    wield_map = _coerce_dict(payload.get("wielded_by_class"))
    for cls, entry in wield_map.items():
        if isinstance(entry, dict):
            for key in ("wielded", "weapon", "iid", "instance_id"):
                if isinstance(entry.get(key), str):
                    entry[key] = _remap_scalar(entry[key], assigner)
        elif isinstance(entry, str):
            wield_map[cls] = _remap_scalar(entry, assigner)
    if wield_map:
        payload["wielded_by_class"] = wield_map

    for key in ("wielded", "weapon"):
        if isinstance(payload.get(key), str):
            payload[key] = _remap_scalar(payload[key], assigner)

    armour_block = payload.get("armour") or payload.get("armor")
    if isinstance(armour_block, dict):
        for key in ("wearing", "iid", "instance_id"):
            if isinstance(armour_block.get(key), str):
                armour_block[key] = _remap_scalar(armour_block[key], assigner)
    elif isinstance(armour_block, str):
        payload["armour"] = _remap_scalar(armour_block, assigner)

    active = payload.get("active")
    if isinstance(active, dict):
        _remap_player_payload(active, assigner, canonical=False)

    players = payload.get("players")
    if isinstance(players, list):
        for entry in players:
            if isinstance(entry, dict):
                _remap_player_payload(entry, assigner, canonical=False)


def _remap_monster_inventory(items: Iterable[Any], assigner: IIDAssigner, *, consume: bool) -> None:
    counters: Dict[str, int] = defaultdict(int)
    for entry in items:
        if not isinstance(entry, MutableMapping):
            continue
        token = _instance_id(entry)
        if not token:
            continue
        if consume:
            new_id = assigner.assign_next(token)
        else:
            idx = counters[token]
            new_id = assigner.reuse_for_sequence(token, idx)
            counters[token] = idx + 1
        entry["instance_id"] = new_id
        entry["iid"] = new_id


def _remap_monster_payload(payload: MutableMapping[str, Any], assigner: IIDAssigner, *, canonical: bool) -> None:
    inventory = payload.get("inventory")
    if isinstance(inventory, list):
        _remap_monster_inventory(inventory, assigner, consume=canonical)

    bag = payload.get("bag")
    if isinstance(bag, list):
        _remap_monster_inventory(bag, assigner, consume=canonical)

    armour = payload.get("armour_wearing")
    if isinstance(armour, str):
        payload["armour_wearing"] = _remap_scalar(armour, assigner, latest=True)

    armour_slot = payload.get("armour_slot")
    if isinstance(armour_slot, dict):
        token = armour_slot.get("iid") or armour_slot.get("instance_id")
        if isinstance(token, str) and token:
            new_id = _remap_scalar(token, assigner, latest=True)
            armour_slot["iid"] = new_id
            armour_slot["instance_id"] = new_id

    for key in ("wielded", "weapon"):
        if isinstance(payload.get(key), str):
            payload[key] = _remap_scalar(payload[key], assigner, latest=True)


def _resolve_items_path(state_dir: Path) -> Path:
    primary = state_dir / "items" / "instances.json"
    if primary.exists():
        return primary
    fallback = state_dir / "instances.json"
    return fallback if fallback.exists() else primary


def _load_items_state(state_dir: Path) -> tuple[Path, Any, List[MutableMapping[str, Any]]]:
    path = _resolve_items_path(state_dir)
    data = _load_json(path)
    if isinstance(data, dict) and "instances" in data:
        items = _coerce_list(data.get("instances"))
    elif isinstance(data, list):
        items = data  # type: ignore[assignment]
    else:
        items = []
    return path, data, [dict(inst) for inst in items]


def _persist_items(path: Path, original: Any, items: List[MutableMapping[str, Any]]) -> None:
    if isinstance(original, dict) and "instances" in original:
        payload = dict(original)
        payload["instances"] = items
    else:
        payload = items
    _save_json(path, payload)


def _update_player_state(state_dir: Path, assigner: IIDAssigner, *, dry_run: bool) -> bool:
    path = state_dir / "playerlivestate.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        return False

    before = json.dumps(data, sort_keys=True)
    _remap_player_payload(data, assigner, canonical=True)
    after = json.dumps(data, sort_keys=True)
    if before == after or dry_run:
        return before != after
    _save_json(path, data)
    return True


def _update_monsters_state(state_dir: Path, assigner: IIDAssigner, *, dry_run: bool) -> bool:
    path = state_dir / "monsters" / "instances.json"
    data = _load_json(path)
    if data is None:
        return False

    changed = False
    if isinstance(data, dict) and "instances" in data:
        payload = _coerce_list(data.get("instances"))
        for entry in payload:
            if isinstance(entry, dict):
                _remap_monster_payload(entry, assigner, canonical=True)
        if not dry_run:
            new_blob = dict(data)
            new_blob["instances"] = payload
            _save_json(path, new_blob)
        changed = True
    elif isinstance(data, dict) and "monsters" in data:
        monsters = _coerce_list(data.get("monsters"))
        for entry in monsters:
            if isinstance(entry, dict):
                _remap_monster_payload(entry, assigner, canonical=True)
        if not dry_run:
            new_blob = dict(data)
            new_blob["monsters"] = monsters
            _save_json(path, new_blob)
        changed = True
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                _remap_monster_payload(entry, assigner, canonical=True)
        if not dry_run:
            _save_json(path, data)
        changed = True
    else:
        return False

    return changed


def repair(state_dir: Path, *, dry_run: bool = False) -> Dict[str, Any]:
    state_dir = Path(state_dir)
    items_path, original, items = _load_items_state(state_dir)
    replacements, mutated = _remint_instances(items)

    if mutated and not dry_run:
        _persist_items(items_path, original, items)

    assigner = IIDAssigner(replacements)

    player_changed = _update_player_state(state_dir, assigner, dry_run=dry_run)
    monsters_changed = _update_monsters_state(state_dir, assigner, dry_run=dry_run)

    return {
        "items_path": str(items_path),
        "reminted": replacements,
        "items_changed": mutated,
        "player_changed": player_changed,
        "monsters_changed": monsters_changed,
        "dry_run": dry_run,
    }


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Repair duplicate item instance IDs.")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("state"),
        help="Path to the game state directory (default: ./state)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = repair(args.state_dir, dry_run=args.dry_run)
    reminted = sum(max(0, len(seq) - 1) for seq in report["reminted"].values())

    print(f"Scanned {report['items_path']}")
    if reminted:
        print(f"Reminted {reminted} duplicate iid(s).")
    else:
        print("No duplicate iids detected.")
    if report["items_changed"]:
        print("Items state updated.")
    if report["player_changed"]:
        print("Player state references rewritten.")
    if report["monsters_changed"]:
        print("Monster state references rewritten.")
    if args.dry_run:
        print("(dry-run: no files were written)")


if __name__ == "__main__":  # pragma: no cover - manual execution entry
    main()
