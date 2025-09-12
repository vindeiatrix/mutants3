# UI Invariants

- Hyphenated tokens never break at `-`, and leading articles stay bound to the
  first token. After article and numbering are applied, final display strings
  replace `-` with U+2011 and the article space with U+00A0 before wrapping.
  This applies uniformly to ground and inventory displays; canonical names
  remain ASCII and unchanged.
- All UI wrapping uses Python's `TextWrapper` with `break_on_hyphens=False`,
  `break_long_words=False`, `replace_whitespace=False`, and
  `drop_whitespace=False`.

