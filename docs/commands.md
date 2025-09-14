# Commands

## Throw

`throw <direction> <item>` throws an item into an adjacent tile. Item names
support unique prefixes, so `throw n nuc` will throw the Nuclear-Decay north if
it's the only match. Thrown items always leave your inventory. If the throw is
blocked (no exit, closed gate, or map boundary) the item lands at your feet.
Throw uses the same passability rules as movement for consistency.

### Input normalization
All item-token parsing should use `normalize_item_query()` from `mutants.util.textnorm`.
This guarantees consistent behavior across commands (debug/use/equip/throw) and lets us evolve
the normalization rules in one place.
