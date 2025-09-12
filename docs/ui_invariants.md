# UI Invariants

- Hyphenated tokens never wrap at `-`.
- All UI wrapping uses Python's `TextWrapper` with `break_on_hyphens=False`,
  `break_long_words=False`, `replace_whitespace=False`, and
  `drop_whitespace=False`.
- Rendered item names replace ASCII hyphen with U+2011 (no-break hyphen) to
  ensure they never split across lines.

