from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Set, TextIO

from mutants.io.atomic import atomic_write_json
from mutants.services import monsters_state


@dataclass
class RecordResult:
    index: int
    label: str
    status: str = "OK"
    messages: List[str] = field(default_factory=list)
    source_id: Optional[str] = None
    final_id: Optional[str] = None
    pinned_years: List[int] = field(default_factory=list)
    minted_iids: int = 0


@dataclass
class ImportReport:
    records: List[RecordResult]
    normalized_new: List[Dict[str, Any]]
    combined_payload: List[Dict[str, Any]]
    per_year: Dict[int, int]
    minted_iids: int

    @property
    def imported_count(self) -> int:
        return sum(1 for r in self.records if r.status == "OK")

    @property
    def rejected_count(self) -> int:
        return sum(1 for r in self.records if r.status != "OK")


class MonsterImportError(Exception):
    """Raised when the import payload is malformed."""


def _load_input(path: Path) -> List[Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - explicit signal to caller
        raise MonsterImportError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:  # pragma: no cover - explicit signal to caller
        raise MonsterImportError(f"Invalid JSON in {path}: {exc}") from exc

    if isinstance(raw, Mapping) and "monsters" in raw:
        candidates = raw.get("monsters")
    else:
        candidates = raw

    if not isinstance(candidates, list):
        raise MonsterImportError("Monster import payload must be a JSON array.")

    return list(candidates)


def _extract_item_id(item: Mapping[str, Any]) -> str:
    for key in ("item_id", "id", "catalog_id"):
        raw = item.get(key)
        if isinstance(raw, str) and raw:
            return raw
    return ""


def _collect_item_iids(record: Mapping[str, Any]) -> Set[str]:
    iids: Set[str] = set()
    bag = record.get("bag")
    if isinstance(bag, Iterable):
        for item in bag:
            if not isinstance(item, Mapping):
                continue
            iid = item.get("iid") or item.get("instance_id")
            if isinstance(iid, str) and iid:
                iids.add(iid)
    armour = record.get("armour_slot")
    if isinstance(armour, Mapping):
        iid = armour.get("iid") or armour.get("instance_id")
        if isinstance(iid, str) and iid:
            iids.add(iid)
    return iids


def _normalize_label(payload: Mapping[str, Any], idx: int) -> str:
    label = (
        payload.get("name")
        or payload.get("monster_id")
        or payload.get("id")
        or f"record#{idx}"
    )
    return str(label)


def _validate_record(
    payload: Any,
    *,
    idx: int,
    existing_ids: Set[str],
    file_ids: Set[str],
) -> tuple[Optional[Dict[str, Any]], RecordResult, Set[str]]:
    result = RecordResult(index=idx, label=_normalize_label(payload if isinstance(payload, Mapping) else {}, idx))

    if not isinstance(payload, Mapping):
        result.status = "ERROR"
        result.messages.append("Entry must be an object.")
        return None, result, set()

    record: Dict[str, Any] = dict(payload)
    bag_raw = record.get("bag")
    errors: List[str] = []
    notes: List[str] = []

    pinned_years_raw = record.get("pinned_years")
    normalized_years: List[int] = []
    has_any_years = isinstance(pinned_years_raw, list) and bool(pinned_years_raw)
    if has_any_years:
        for entry in pinned_years_raw:
            coerced = _coerce_int(entry)
            if coerced is None:
                notes.append(f"ignored pinned_year value: {entry}")
                continue
            normalized_years.append(coerced)

    if not normalized_years:
        if has_any_years:
            errors.append("no valid pinned_years")
        else:
            errors.append("pinned_years missing or empty")

    record["pinned_years"] = normalized_years
    result.pinned_years = list(normalized_years)

    bag_items: List[Dict[str, Any]] = []
    if bag_raw is None:
        record["bag"] = []
    elif not isinstance(bag_raw, list):
        errors.append("bag must be an array")
    else:
        for pos, item in enumerate(bag_raw):
            if not isinstance(item, Mapping):
                errors.append(f"bag[{pos}] must be an object")
                continue
            item_dict = dict(item)
            if not _extract_item_id(item_dict):
                errors.append(f"bag[{pos}] missing item_id")
                continue
            bag_items.append(item_dict)
        record["bag"] = bag_items

    armour_raw = record.get("armour_slot")
    armour_item: Optional[Dict[str, Any]] = None
    if armour_raw is None or armour_raw is False:
        record["armour_slot"] = None
    elif not isinstance(armour_raw, Mapping):
        errors.append("armour_slot must be an object or null")
        record["armour_slot"] = None
    else:
        armour_item = dict(armour_raw)
        if not _extract_item_id(armour_item):
            errors.append("armour_slot missing item_id")
            armour_item = None
        record["armour_slot"] = armour_item

    if armour_item and bag_items:
        armour_key = armour_item.get("iid") or armour_item.get("item_id")
        if isinstance(armour_key, str) and armour_key:
            filtered: List[Dict[str, Any]] = []
            removed = False
            for item in bag_items:
                key = item.get("iid") or item.get("item_id")
                if key == armour_key:
                    removed = True
                    continue
                filtered.append(item)
            if removed:
                notes.append("removed armour_slot item from bag")
                record["bag"] = filtered
                bag_items = filtered

    valid_iids = {item.get("iid") for item in bag_items if isinstance(item, Mapping) and isinstance(item.get("iid"), str) and item.get("iid")}
    valid_item_ids = {_extract_item_id(item) for item in bag_items if isinstance(item, Mapping)}

    wielded_raw = record.get("wielded")
    if wielded_raw is None or wielded_raw == "":
        record["wielded"] = None
    elif isinstance(wielded_raw, str):
        if wielded_raw in valid_iids or wielded_raw in valid_item_ids:
            record["wielded"] = wielded_raw
        else:
            record["wielded"] = None
            notes.append(f"wielded cleared (not in bag: {wielded_raw})")
    else:
        record["wielded"] = None
        notes.append("wielded cleared (invalid type)")

    raw_id = record.get("id")
    if isinstance(raw_id, str) and raw_id:
        candidate_id = raw_id
        if candidate_id in existing_ids:
            errors.append(f"duplicate id (existing): {candidate_id}")
        elif candidate_id in file_ids:
            errors.append(f"duplicate id: {candidate_id}")
        else:
            file_ids.add(candidate_id)
            result.source_id = candidate_id
    elif raw_id is not None:
        # Normalize non-string ids by coercing to string for downstream normalization.
        candidate_id = str(raw_id)
        if candidate_id in existing_ids or candidate_id in file_ids:
            errors.append(f"duplicate id: {candidate_id}")
        else:
            file_ids.add(candidate_id)
            result.source_id = candidate_id
            record["id"] = candidate_id
    else:
        record.pop("id", None)

    if errors:
        result.status = "ERROR"
        result.messages = errors
        return None, result, set()

    if notes:
        result.messages.extend(notes)

    return record, result, _collect_item_iids(record)


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count_minted_iids(original: Set[str], normalized: Mapping[str, Any]) -> int:
    new = _collect_item_iids(normalized)
    return len(new - original)


def run_import(
    input_path: Path,
    *,
    dry_run: bool,
    state_path: Path | None = None,
) -> ImportReport:
    entries = _load_input(input_path)

    target_path = Path(state_path) if state_path is not None else monsters_state.DEFAULT_MONSTERS_PATH
    state = monsters_state.load_state(target_path)
    existing_monsters = [dict(m) for m in state.list_all()]
    existing_ids: Set[str] = {
        str(m["id"])
        for m in existing_monsters
        if isinstance(m, Mapping) and m.get("id")
    }

    file_ids: Set[str] = set()
    records: List[RecordResult] = []
    valid_records: List[Dict[str, Any]] = []
    valid_results: List[RecordResult] = []
    original_iids: List[Set[str]] = []

    for idx, payload in enumerate(entries):
        record, result, orig_iids = _validate_record(
            payload,
            idx=idx,
            existing_ids=existing_ids,
            file_ids=file_ids,
        )
        records.append(result)
        if record is None:
            continue
        valid_records.append(record)
        valid_results.append(result)
        original_iids.append(orig_iids)

    try:
        catalog = monsters_state.items_catalog.load_catalog()
    except FileNotFoundError:
        catalog = {}

    combined = existing_monsters + valid_records
    normalized_all = monsters_state.normalize_records(combined, catalog=catalog)
    normalized_new = normalized_all[len(existing_monsters) :]

    minted_total = 0
    for idx, normalized in enumerate(normalized_new):
        result = valid_results[idx]
        result.final_id = str(normalized.get("id") or "") or None
        result.pinned_years = list(normalized.get("pinned_years") or [])
        minted = _count_minted_iids(original_iids[idx], normalized)
        result.minted_iids = minted
        minted_total += minted
        if result.status == "OK":
            if result.source_id and result.final_id and result.source_id != result.final_id:
                result.messages.append(f"id normalized to {result.final_id}")
            if not result.source_id and result.final_id:
                result.messages.append(f"id minted as {result.final_id}")
            if minted:
                suffix = "iid" if minted == 1 else "iids"
                result.messages.append(f"minted {minted} {suffix}")

    per_year_counter: Dict[int, int] = defaultdict(int)
    for normalized in normalized_new:
        years = normalized.get("pinned_years")
        if isinstance(years, Iterable):
            for year in years:
                coerced = _coerce_int(year)
                if coerced is not None:
                    per_year_counter[coerced] += 1

    per_year = dict(sorted(per_year_counter.items()))

    report = ImportReport(
        records=records,
        normalized_new=normalized_new,
        combined_payload=normalized_all,
        per_year=per_year,
        minted_iids=minted_total,
    )

    if not dry_run:
        payload = {"monsters": report.combined_payload}
        atomic_write_json(target_path, payload)
        monsters_state.invalidate_cache()

    return report


def format_report_table(records: List[RecordResult]) -> str:
    headers = ["#", "Monster", "Status", "ID", "Notes"]
    rows: List[List[str]] = []
    for rec in records:
        ident = rec.final_id or rec.source_id or ""
        notes = "; ".join(rec.messages)
        rows.append([
            str(rec.index),
            rec.label,
            rec.status,
            ident,
            notes,
        ])

    widths = [len(col) for col in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    header_line = " | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers)))
    separator = "-+-".join("-" * widths[idx] for idx in range(len(headers)))
    data_lines = [
        " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers)))
        for row in rows
    ]

    if rows:
        return "\n".join([header_line, separator, *data_lines])
    return header_line


def print_report(report: ImportReport, *, dry_run: bool, out: TextIO = sys.stdout) -> None:
    table = format_report_table(report.records)
    out.write(f"{table}\n")
    out.write("\n")

    if report.imported_count:
        out.write(f"Imported {report.imported_count} monster(s).\n")
        if report.per_year:
            out.write("Per year:\n")
            for year, count in report.per_year.items():
                out.write(f"  {year}: {count}\n")
        out.write(f"Minted {report.minted_iids} item IID(s).\n")

    if report.rejected_count:
        out.write(f"Rejected {report.rejected_count} monster(s).\n")

    if dry_run:
        out.write("Dry-run: no changes were written.\n")
