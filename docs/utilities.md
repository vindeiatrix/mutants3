# Utilities and Shared Services

This document lists core helpers and cross-cutting services that all commands
and systems should use. Referencing this page prevents "re-inventing" logic.

---

## Item Token Normalization

**Function:** `mutants.util.textnorm.normalize_item_query(s: str) -> str`

- Normalizes user input into canonical, hyphenated tokens.
- Handles:
  - Lowercasing
  - Stripping quotes and whitespace
  - Removing leading articles (`a`, `an`, `the`)
  - Normalizing Unicode punctuation (e.g., en/em dashes)
  - Converting non-alphanumeric runs to `-`

**Examples:**
- `"A  Nuclear–Thong"` → `nuclear-thong`
- `the Nuclear Thong` → `nuclear-thong`
- `NUCLEAR-TH` → `nuclear-th`

**Usage:**
- Must be applied in all item-related commands (`debug add item`, `throw`,
  `equip`, `use`).
- Do not write ad-hoc regex; always import this helper.

---

## Direction Token Resolver

**Function:** `mutants.util.directions.resolve_dir(token: str) -> str | None`

- Resolves a user-entered direction token to `"north"`, `"south"`,
  `"east"`, or `"west"`.
- Accepts any prefix of the full word, case-insensitively (`we` → `west`,
  `nor` → `north`).

**Examples:**
- `resolve_dir("w")` → `"west"`
- `resolve_dir("sou")` → `"south"`
- `resolve_dir("")` → `None`

**Usage:**
- All direction parsing—standalone movement and command arguments—must use this
  resolver. Do not implement per-command direction logic.

---

## Passability Service

- The service that determines if movement (or throwing) can proceed in a given
  direction.
- Centralized logic: gates, map boundaries, spell effects (walls of ice, ion
  fields), etc.
- **Rule:** Any mechanic that tests "can I go in that direction?" must use this
  service. Throw relies on it just like movement.

---

## Logging Sink

**Class:** `mutants.ui.logsink.LogSink`

- Unified interface for recording events.
- Preferred API: `add(kind, text, ts)`
- Legacy shim: `handle(ev: dict)` for callers passing dicts.
- Do not roll your own logging; always go through the sink.

---

## Why These Matter

These utilities make behavior consistent across the codebase. If new features
need item parsing, passability checks, or logs, they *must* reference these
helpers. Update this doc when new utilities are introduced.
