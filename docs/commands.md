# Commands

## Prefix Matching

Commands are case-insensitive and accept unique prefixes once you type at least
three characters. If two commands share the same three-letter prefix you must
type one more letter to disambiguate. Single-letter shortcuts remain available
only when explicitly aliased (e.g. `x` to open the class selection menu).

## Quit

Type `quit` (or the prefix `qui`/`q`) to save and exit from anywhere.

## Movement

Typing a direction moves you to an adjacent tile. Any prefix of the full word
is accepted, case-insensitively: `w`/`we`/`wes`/`west`,
`n`/`no`/`nor`/`nort`/`north`, and similarly for `east` and `south`.
Movement updates your compass location `[year, x, y]` through the
`StateManager`, and the coordinates persist to `state/savegame.json` on
autosave or clean exit.

## Look

`look` shows the current room. `look <direction>` peeks into an adjacent tile
without moving. Direction arguments accept any prefix of the full word (e.g.
`look we` peeks west).

## Get

`get <item>` picks up an item from the ground. Item names are parsed via the
normalization helper (see [utilities](utilities.md)). If multiple ground items
match the prefix, the first one in the ground list is picked up.

## Throw

`throw <direction> <item>` throws an item into an adjacent tile. Direction
arguments accept any prefix of the full word, e.g. `throw we ion-p` throws the
Ion-Pistol west. Item names support unique prefixes, so `throw n nuc` will throw
the Nuclear-Decay north if it's the only match. If the item token matches
multiple items in your inventory, throw picks the first match in inventory
order. Thrown items always leave your inventory. If the throw is blocked (no
exit, closed gate, or map boundary) the item lands at your feet. Throw uses the
same passability rules as movement for consistency. Item names are parsed via
the normalization helper (see [utilities](utilities.md)).

## Open

`open <direction>` reopens a closed gate. Direction arguments accept any prefix
of the full word (e.g. `open no` opens the north gate).

## Close

`close <direction>` closes an adjacent gate. Direction arguments accept any
prefix of the full word (e.g. `close so` closes the south gate).

## Debug Add Item

`debug add item <name>` spawns an item into your inventory. Item names are
parsed via the normalization helper (see [utilities](utilities.md)).

## Statistics

`statistics` (or any prefix such as `sta`, `stat`, `stati`, …) shows the active
player's level, HP, AC, experience, money, ability scores, active conditions,
and current location. The command is read-only.

## Class Selection

Press `x` from in-game mode to save and return to the class selection menu.
From the menu you can pick a new class by entering `1`–`5` or type `?` for a
quick reminder. `BURY <n>` is accepted but currently replies with “Bury not
implemented yet.”

## Equip

`equip <item>` equips an item from your inventory. Item names are parsed via
the normalization helper (see [utilities](utilities.md)).

## Use

`use <item>` activates an item's effect. Item names are parsed via the
normalization helper (see [utilities](utilities.md)).
