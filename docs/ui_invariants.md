# UI Invariants

- Hyphenated tokens never break at `-`, and leading articles stay bound to the
  first token. After article and numbering are applied, final display strings
  replace `-` with U+2011 and the article space with U+00A0 before wrapping.
  This applies uniformly to ground and inventory displays; canonical names
  remain ASCII and unchanged.
- All UI wrapping uses Python's `TextWrapper` with `break_on_hyphens=False`,
  `break_long_words=False`, `replace_whitespace=False`, and
  `drop_whitespace=False`.

## Command-Argument UX Invariants (new)
- Commands with `arg_policy=required` **must not** act when invoked without an argument; they emit a usage line via the feedback bus.
- Invalid subjects produce **specific** warnings (e.g., ground vs. inventory: “There isn’t a {subject} here.” vs. “You’re not carrying a {subject}. ”); generic “Nothing happens.” should not be used for these cases.
- On success, commands emit an explicit confirmation line including the resolved subject name when available.
- **Armor**: worn armor is **not** part of inventory and is not targetable by these commands; only `remove` interacts with the armor slot.

## Command Routing Invariants (new)
- Tokens of **≥3 letters** resolve to a **unique** command by prefix; **<3** works only for explicit aliases (default: `n/s/e/w`).
- Ambiguous ≥3 prefixes must produce a **single warning** and no action.

## Positional-Args Invariants (new)
- Two-argument commands declare ordered arg kinds; missing args result in a **usage** message; parse errors map to stable **reason codes** (e.g., `invalid_direction`, `invalid_amount_range`, `wrong_item_literal`).
- Inventory arg kinds **exclude worn armor**; only `remove` may act on armor.

## Throw UX (new)
- `throw [direction] [item]` behaves like dropping that item onto the adjacent tile. It never renders a tile; it pushes feedback:
  - Success: “You throw the {item} {dir}.”
  - Invalid direction / no neighbor: “You can’t throw that way.”
  - Not carrying / armor: same messages as `drop`.

