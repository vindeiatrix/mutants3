# Changelog

## [Unreleased]

- Fix: Ground item list no longer breaks hyphenated names across lines.
- Hardening: Item display names render hyphens as U+2011 (no-break hyphen) to
  resist misconfigured wrappers.
- Change: `get`/`drop` now require a subject argument; typing them alone shows usage instead of acting implicitly.
- UX: `get`/`drop` emit explicit success feedback with item names, and clearer invalid messages (“There isn’t a {subject} here.” / “You’re not carrying a {subject}. ”). Worn armor remains excluded from inventory operations (only `remove` can affect armor).
- Router: All commands accept **≥3-letter unique prefixes** (case-insensitive). Only **north/south/east/west** keep one-letter forms (`n/s/e/w`). Ambiguous prefixes now warn and do nothing.
- Framework: Added positional-args runner for two-argument commands (POINT/THROW and the restricted `BUY ions [100000-999999]` at maintenance shops); docs and minimal tests included.

