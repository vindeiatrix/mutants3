# Commands

## Throw

`throw <direction> <item>` throws an item into an adjacent tile. Item names
support unique prefixes, so `throw n nuc` will throw the Nuclear-Decay north if
it's the only match. Thrown items always leave your inventory. If the throw is
blocked (no exit, closed gate, or map boundary) the item lands at your feet.
Throw uses the same passability rules as movement for consistency. Item names
are parsed via the normalization helper (see [utilities](utilities.md)).

## Debug Add Item

`debug add item <name>` spawns an item into your inventory. Item names are
parsed via the normalization helper (see [utilities](utilities.md)).

## Equip

`equip <item>` equips an item from your inventory. Item names are parsed via
the normalization helper (see [utilities](utilities.md)).

## Use

`use <item>` activates an item's effect. Item names are parsed via the
normalization helper (see [utilities](utilities.md)).
