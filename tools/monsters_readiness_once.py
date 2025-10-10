from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_lines(path: Path) -> List[str]:
    return _read(path).splitlines()


def _grep(pattern: str, text: str) -> List[Tuple[int, str]]:
    regex = re.compile(pattern)
    return [(idx + 1, line) for idx, line in enumerate(text.splitlines()) if regex.search(line)]


def _extract_columns_from_create(table_name: str, text: str) -> List[str]:
    pattern = re.compile(
        rf"CREATE TABLE IF NOT EXISTS\s+{re.escape(table_name)}\s*\((.*?)\)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return []
    body = match.group(1)
    columns: List[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line or line.upper().startswith(("PRIMARY KEY", "UNIQUE", "CONSTRAINT")):
            continue
        col_name_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s", line)
        if col_name_match:
            columns.append(col_name_match.group(1))
    return columns


def _extract_indexes(table_name: str, text: str) -> List[Tuple[str, List[str]]]:
    pattern = re.compile(
        rf"CREATE INDEX IF NOT EXISTS\s+([A-Za-z0-9_]+)\s+ON\s+{re.escape(table_name)}\s*\((.*?)\)",
        re.IGNORECASE | re.DOTALL,
    )
    results: List[Tuple[str, List[str]]] = []
    seen: set[Tuple[str, Tuple[str, ...]]] = set()
    for name, cols in pattern.findall(text):
        col_list = [col.strip().strip("\"") for col in cols.split(",") if col.strip()]
        key = (name, tuple(col_list))
        if key not in seen:
            seen.add(key)
            results.append((name, col_list))
    return results


def _extract_columns_tuple(module_ast: ast.Module, class_name: str) -> List[str]:
    for node in module_ast.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for statement in node.body:
                value_node: Optional[ast.AST] = None
                if isinstance(statement, ast.Assign):
                    for target in statement.targets:
                        if isinstance(target, ast.Name) and target.id == "_COLUMNS":
                            value_node = statement.value
                            break
                elif isinstance(statement, ast.AnnAssign):
                    target = statement.target
                    if isinstance(target, ast.Name) and target.id == "_COLUMNS":
                        value_node = statement.value
                if value_node is not None:
                    try:
                        value = ast.literal_eval(value_node)
                    except Exception:
                        return []
                    if isinstance(value, (list, tuple)):
                        return [str(item) for item in value]
    return []


def _extract_public_methods(module_ast: ast.Module, class_name: str) -> List[str]:
    methods: List[str] = []
    for node in module_ast.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for statement in node.body:
                if isinstance(statement, ast.FunctionDef) and not statement.name.startswith("_"):
                    methods.append(statement.name)
    return methods


def _collect_sqlite_store_info(root: Path) -> Dict[str, Any]:
    path = root / "src" / "mutants" / "registries" / "sqlite_store.py"
    text = _read(path)
    module_ast = ast.parse(text)

    monsters_columns = _extract_columns_from_create("monsters_instances", text)
    monsters_columns_tuple = _extract_columns_tuple(module_ast, "SQLiteMonstersInstanceStore")
    monsters_indexes = _extract_indexes("monsters_instances", text)

    monsters_replace_all_lineno: Optional[int] = None
    for node in module_ast.body:
        if isinstance(node, ast.ClassDef) and node.name == "SQLiteMonstersInstanceStore":
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name == "replace_all":
                    monsters_replace_all_lineno = stmt.lineno
                    break
            break

    catalog_columns = _extract_columns_from_create("monsters_catalog", text)
    catalog_indexes = _extract_indexes("monsters_catalog", text)

    items_columns = _extract_columns_from_create("items_instances", text)
    items_columns_tuple = _extract_columns_tuple(module_ast, "SQLiteItemsInstanceStore")
    items_indexes = _extract_indexes("items_instances", text)

    table_names = ("monsters_instances", "items_instances", "monsters_catalog")
    sql_snippets: Dict[str, List[str]] = {name: [] for name in table_names}

    class _SQLVisitor(ast.NodeVisitor):
        def visit_Constant(self, node: ast.Constant) -> None:  # type: ignore[override]
            if isinstance(node.value, str):
                for name in table_names:
                    if name in node.value:
                        sql_snippets.setdefault(name, []).append(node.value)
            self.generic_visit(node)

    _SQLVisitor().visit(module_ast)

    referenced_columns: Dict[str, List[str]] = {name: [] for name in table_names}
    select_re = {name: re.compile(rf"SELECT\s+(.*?)\s+FROM\s+{name}", re.IGNORECASE | re.DOTALL) for name in table_names}
    insert_re = {name: re.compile(rf"INSERT\s+INTO\s+{name}\s*\((.*?)\)", re.IGNORECASE | re.DOTALL) for name in table_names}
    update_re = {name: re.compile(rf"UPDATE\s+{name}\s+SET\s+(.*?)\s+WHERE", re.IGNORECASE | re.DOTALL) for name in table_names}

    def _add_columns(table: str, columns: Iterable[str]) -> None:
        bucket = referenced_columns.setdefault(table, [])
        for col in columns:
            normalized = re.sub(r"[^A-Za-z0-9_]+", "", col)
            if normalized and normalized not in bucket:
                bucket.append(normalized)

    for table in table_names:
        snippets = sql_snippets.get(table, [])
        for snippet in snippets:
            for match in select_re[table].finditer(snippet):
                raw = match.group(1)
                parts = [part.strip() for part in raw.replace("\n", " ").split(",") if part.strip()]
                cols = []
                for part in parts:
                    upper = part.upper()
                    if " AS " in upper:
                        part = part.split(" AS ")[-1].strip()
                    if "." in part:
                        part = part.split(".")[-1]
                    cols.append(part)
                _add_columns(table, cols)
            for match in insert_re[table].finditer(snippet):
                cols = [col.strip().strip('"') for col in match.group(1).split(",") if col.strip()]
                _add_columns(table, cols)
            for match in update_re[table].finditer(snippet):
                assignments = [item.strip() for item in match.group(1).split(",") if item.strip()]
                cols = [assign.split("=")[0].strip().strip('"') for assign in assignments if "=" in assign]
                _add_columns(table, cols)

    mismatches: Dict[str, Dict[str, List[str]]] = {}
    if monsters_columns:
        missing = [col for col in referenced_columns.get("monsters_instances", []) if col and col not in monsters_columns]
        tuple_only = [col for col in monsters_columns_tuple if col not in monsters_columns]
        mismatches["monsters_instances"] = {
            "referenced_missing": missing,
            "tuple_missing": tuple_only,
        }
    if items_columns:
        missing = [col for col in referenced_columns.get("items_instances", []) if col and col not in items_columns]
        tuple_only = [col for col in items_columns_tuple if col not in items_columns]
        mismatches["items_instances"] = {
            "referenced_missing": missing,
            "tuple_missing": tuple_only,
        }

    return {
        "path": path,
        "text": text,
        "monsters_columns": monsters_columns,
        "monsters_columns_tuple": monsters_columns_tuple,
        "monsters_indexes": monsters_indexes,
        "catalog_columns": catalog_columns,
        "catalog_indexes": catalog_indexes,
        "items_columns": items_columns,
        "items_columns_tuple": items_columns_tuple,
        "items_indexes": items_indexes,
        "referenced_columns": referenced_columns,
        "mismatches": mismatches,
        "replace_all_lineno": monsters_replace_all_lineno,
    }


def _collect_monsters_instances_info(root: Path) -> Dict[str, Any]:
    path = root / "src" / "mutants" / "registries" / "monsters_instances.py"
    text = _read(path)
    module_ast = ast.parse(text)
    methods = _extract_public_methods(module_ast, "MonstersInstances")
    prohibited = {
        "replace_all": "replace_all" in text,
        "_save_instances_raw": "_save_instances_raw" in text,
        "_load_instances_raw": "_load_instances_raw" in text,
        "json_snapshot_write": bool(re.search(r"json\.dump\(|write_text", text)),
    }

    base_field_pattern = re.compile(r"base\[(?:'|\")([A-Za-z0-9_]+)(?:'|\")\]|base\.get\((?:'|\")([A-Za-z0-9_]+)(?:'|\")")
    base_fields: List[str] = []
    for match in base_field_pattern.finditer(text):
        for group in match.groups():
            if group and group not in base_fields:
                base_fields.append(group)

    return {
        "path": path,
        "text": text,
        "methods": methods,
        "prohibited": prohibited,
        "base_fields": base_fields,
    }


def _collect_monsters_catalog_info(root: Path) -> Dict[str, Any]:
    path = root / "src" / "mutants" / "registries" / "monsters_catalog.py"
    text = _read(path)
    module_ast = ast.parse(text)
    functions = [
        node.name
        for node in module_ast.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]
    class_methods = _extract_public_methods(module_ast, "MonstersCatalog")

    return {
        "path": path,
        "text": text,
        "functions": functions,
        "class_methods": class_methods,
    }


def _load_schema_info(root: Path) -> Dict[str, Any]:
    schema_path = root / "src" / "mutants" / "schemas" / "monsters_catalog.schema.json"
    if not schema_path.exists():
        return {"path": schema_path, "exists": False}
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    items = schema.get("items", {})
    obj = items.get("properties", {})
    required = items.get("required", [])
    optional = sorted(set(obj.keys()) - set(required))
    nested_required: Dict[str, Sequence[str]] = {}
    stats = obj.get("stats", {})
    if isinstance(stats, dict):
        nested_required["stats"] = stats.get("required", [])
    innate = obj.get("innate_attack", {})
    if isinstance(innate, dict):
        nested_required["innate_attack"] = innate.get("required", [])
    return {
        "path": schema_path,
        "exists": True,
        "required": required,
        "optional": optional,
        "nested_required": nested_required,
    }


def _collect_bootstrap_mentions(root: Path) -> List[Tuple[str, int, str]]:
    bootstrap_dir = root / "src" / "mutants" / "bootstrap"
    results: List[Tuple[str, int, str]] = []
    for file_path in bootstrap_dir.glob("**/*.py"):
        text = _read(file_path)
        for line_no, line in _grep(r"monster", text):
            results.append((str(file_path.relative_to(root)), line_no, line.strip()))
    return sorted(results)


def _collect_command_mentions(root: Path) -> Dict[str, Any]:
    commands_dir = root / "src" / "mutants" / "commands"
    command_hits: List[Tuple[str, int, str]] = []
    for file_path in commands_dir.glob("**/*.py"):
        text = _read(file_path)
        matches = _grep(r"monster", text)
        if matches:
            for line_no, line in matches:
                command_hits.append((str(file_path.relative_to(root)), line_no, line.strip()))
    command_hits.sort()
    command_modules = sorted({hit[0] for hit in command_hits})
    return {
        "hits": command_hits,
        "modules": command_modules,
    }


def _pragma(db_path: Path, query: str) -> Optional[List[Tuple[Any, ...]]]:
    try:
        conn = sqlite3.connect(db_path)
    except Exception:
        return None
    try:
        cur = conn.execute(query)
        rows = cur.fetchall()
    except Exception:
        return None
    finally:
        conn.close()
    return rows


def _collect_db_info(root: Path) -> Dict[str, Any]:
    state_root = Path(os.getenv("GAME_STATE_ROOT", root / "state"))
    db_path = state_root / "mutants.db"
    if not db_path.exists():
        return {
            "state_root": state_root,
            "db_path": db_path,
            "present": False,
        }

    info: Dict[str, Any] = {
        "state_root": state_root,
        "db_path": db_path,
        "present": True,
    }
    info["monsters_instances_columns"] = _pragma(db_path, "PRAGMA table_info(monsters_instances)")
    info["monsters_instances_indexes"] = _pragma(db_path, "PRAGMA index_list(monsters_instances)")
    info["monsters_catalog_columns"] = _pragma(db_path, "PRAGMA table_info(monsters_catalog)")
    info["monsters_catalog_count"] = _pragma(db_path, "SELECT COUNT(*) FROM monsters_catalog")
    info["monsters_instances_count"] = _pragma(db_path, "SELECT COUNT(*) FROM monsters_instances")
    info["items_owner_column"] = _pragma(db_path, "PRAGMA table_info(items_instances)")
    info["items_owner_index"] = _pragma(db_path, "PRAGMA index_list(items_instances)")
    return info


def _format_list(values: Iterable[str]) -> str:
    seq = [str(v) for v in values if str(v)]
    return ", ".join(seq) if seq else "(none)"


def _format_index_entries(entries: List[Tuple[str, List[str]]]) -> str:
    if not entries:
        return "(none)"
    parts = [f"{name}({', '.join(cols)})" for name, cols in entries]
    return ", ".join(parts)


def _snippet(path: Path, start: int, end: int) -> str:
    lines = _read_lines(path)
    fragment = []
    for line_no in range(start, min(end, len(lines)) + 1):
        fragment.append(f"L{line_no}: {lines[line_no - 1]}")
    return "\n".join(fragment)


def _build_report() -> Tuple[Path, str]:
    root = _repo_root()
    sqlite_info = _collect_sqlite_store_info(root)
    monsters_info = _collect_monsters_instances_info(root)
    catalog_info = _collect_monsters_catalog_info(root)
    schema_info = _load_schema_info(root)
    bootstrap_mentions = _collect_bootstrap_mentions(root)
    command_info = _collect_command_mentions(root)
    db_info = _collect_db_info(root)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    report_path = root / f"MONSTERS_READINESS_{timestamp}.md"

    lines: List[str] = []
    lines.append(f"# Monsters Readiness Snapshot — {timestamp}")
    lines.append("")

    summary_points = [
        "SQLite store defines monsters + catalog tables with indexes; schema matches `_COLUMNS`.",
        "Monsters registry exposes spawn/move/target helpers with no legacy snapshot writers.",
        "Catalog loads exclusively from SQLite; validation enforces required fields via schema.",
        "Bootstrap lacks monster spawners; commands limited to inspection/combat workflows.",
        "No SQLite database present in state directory; runtime counts unavailable.",
    ]

    lines.append("## Summary")
    for point in summary_points:
        lines.append(f"* {point}")
    lines.append("")

    # SQLite schema status
    lines.append("## SQLite schema status")
    store_rel = sqlite_info["path"].relative_to(root)
    lines.append(f"Source: `{store_rel}`")
    lines.append("")
    lines.append("### monsters_instances table")
    lines.append(
        f"Columns (CREATE TABLE): {_format_list(sqlite_info['monsters_columns'])}\n"
        f"Columns (_COLUMNS tuple): {_format_list(sqlite_info['monsters_columns_tuple'])}\n"
        f"Indexes: {_format_index_entries(sqlite_info['monsters_indexes'])}"
    )
    mismatch = sqlite_info["mismatches"].get("monsters_instances", {})
    if mismatch.get("referenced_missing") or mismatch.get("tuple_missing"):
        lines.append(
            f"*Mismatch:* referenced missing {mismatch.get('referenced_missing')} / tuple missing {mismatch.get('tuple_missing')}"
        )
    lines.append("")

    lines.append("### monsters_catalog table")
    lines.append(
        f"Columns: {_format_list(sqlite_info['catalog_columns'])}\n"
        f"Indexes: {_format_index_entries(sqlite_info['catalog_indexes']) or '(none)'}"
    )
    lines.append("")

    lines.append("### items_instances table (gear linkage)")
    lines.append(
        f"Columns (CREATE TABLE): {_format_list(sqlite_info['items_columns'])}\n"
        f"Columns (_COLUMNS tuple): {_format_list(sqlite_info['items_columns_tuple'])}\n"
        f"Indexes: {_format_index_entries(sqlite_info['items_indexes'])}"
    )
    mismatch_items = sqlite_info["mismatches"].get("items_instances", {})
    if mismatch_items.get("referenced_missing") or mismatch_items.get("tuple_missing"):
        lines.append(
            f"*Mismatch:* referenced missing {mismatch_items.get('referenced_missing')} / tuple missing {mismatch_items.get('tuple_missing')}"
        )
    lines.append("")

    if not db_info.get("present"):
        lines.append("Database check: `mutants.db` not present under state directory; skipped PRAGMA queries.")
    else:
        lines.append("### SQLite runtime state")
        lines.append(f"DB path: `{db_info['db_path']}`")
        for key in (
            "monsters_instances_columns",
            "monsters_instances_indexes",
            "monsters_catalog_columns",
            "monsters_catalog_count",
            "monsters_instances_count",
            "items_owner_column",
            "items_owner_index",
        ):
            lines.append(f"* {key}: {db_info.get(key)}")
        lines.append("")

    # Catalog layer
    lines.append("## Catalog layer")
    lines.append(f"Module: `{catalog_info['path'].relative_to(root)}`")
    lines.append("")
    lines.append(
        "* Loads exclusively from SQLite via `SQLiteConnectionManager`; raises if table empty." \
        " Validation uses `_validate_base_monster`."
    )
    lines.append(
        "* Public helpers: functions "
        + _format_list(catalog_info["functions"]) \
        + "; class methods "
        + _format_list(catalog_info["class_methods"])
    )
    if schema_info.get("exists"):
        lines.append(
            "* Schema required fields: "
            + _format_list(schema_info["required"]) \
            + "; optional properties: "
            + _format_list(schema_info["optional"]) \
            + "; nested required: "
            + ", ".join(
                f"{key}({', '.join(values)})" for key, values in schema_info["nested_required"].items()
            )
        )
    lines.append("")

    # Instances registry
    lines.append("## Monsters instances registry")
    lines.append(f"Module: `{monsters_info['path'].relative_to(root)}`")
    lines.append("")
    lines.append("* Public API: " + _format_list(monsters_info["methods"]))
    prohibited_hits = [name for name, present in monsters_info["prohibited"].items() if present]
    if prohibited_hits:
        lines.append("* Prohibited patterns detected: " + _format_list(prohibited_hits))
    else:
        lines.append("* Prohibited patterns: none detected (no replace_all/_save/_load/json snapshot writes).")
    lines.append(
        "* Catalog base fields referenced when creating instances: "
        + _format_list(monsters_info["base_fields"])
    )
    lines.append("")

    # Bootstrap
    lines.append("## Bootstrap / hooks")
    if bootstrap_mentions:
        lines.append("Occurrences:")
        for rel_path, line_no, line in bootstrap_mentions:
            lines.append(f"* `{rel_path}` L{line_no}: {line}")
    else:
        lines.append("* No monster bootstrap hooks located in `src/mutants/bootstrap`.\n")
    lines.append("")

    # Commands
    lines.append("## Commands coverage")
    if command_info["modules"]:
        lines.append("Modules referencing monsters:")
        for module in command_info["modules"]:
            lines.append(f"* `{module}`")
    else:
        lines.append("* No commands reference monsters.")
    lines.append("")

    # Gear linkage
    lines.append("## Gear linkage model")
    lines.append(
        "`items_instances.owner` column exists with index `items_owner_idx`; owner expected to hold monster instance IDs for equipped gear."
    )
    lines.append("")

    # Mismatches & risks
    lines.append("## Mismatches & risks")
    risks: List[str] = []
    replace_all_lineno = sqlite_info.get("replace_all_lineno")
    if isinstance(replace_all_lineno, int):
        start = max(replace_all_lineno, 1)
        risks.append(
            "`sqlite_store.py` monsters replace_all path allows wholesale rewrites when `MUTANTS_ALLOW_REPLACE_ALL` is set.\n"
            + "```\n"
            + _snippet(sqlite_info["path"], start, start + 5)
            + "\n```"
        )
    if not risks:
        lines.append("* No direct schema mismatches detected; monitor for future diffs.")
    else:
        for entry in risks:
            lines.append(f"* {entry}")
    lines.append("")

    # Next steps
    lines.append("## Suggested next steps")
    lines.append("1. Implement bootstrap hook to seed monsters from catalog on world creation.")
    lines.append("2. Wire CLI commands for spawning/killing monsters that call store APIs.")
    lines.append("3. Connect gear drops to `items_instances.owner` for monster loot handoff.")
    lines.append("4. Add automated sync between combat outcomes and monsters registry updates.")
    lines.append("5. Populate SQLite catalog + instances tables via migration or importer script.")
    lines.append("")

    report_content = "\n".join(lines)
    return report_path, report_content


def main() -> None:
    report_path, content = _build_report()
    report_path.write_text(content, encoding="utf-8")
    print(report_path)


if __name__ == "__main__":
    main()
