# UI Invariants

- Hyphenated tokens never break at the hyphen, and articles stay attached to
  the first token. Final UI strings convert "-" to U+2011 and the first space to
  U+00A0 before wrapping. This applies uniformly to ground and inventory
  displays; canonical names remain ASCII and unchanged.
- All UI wrapping uses Python's `TextWrapper` with `break_on_hyphens=False`,
  `break_long_words=False`, `replace_whitespace=False`, and
  `drop_whitespace=False`.

