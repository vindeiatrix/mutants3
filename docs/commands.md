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

## Travel

`travel <year>` (prefixes `tra`/`trav`/`trave`/`travel`) moves you to the
origin of the requested year. Your compass immediately updates to `[year, 0,
0]` without triggering an automatic room render, so you can queue another
action before the next paint. Traveling to the current year is allowed and
currently free; a future update will charge 3,000 Ions per year of distance.

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
player's full BBS-style sheet without triggering a render. A typical output
looks like:

```
Name: Gwydion / Mutant Thief
Exhaustion      : 0
Str: 15     Int: 9     Wis: 8
Dex: 14     Con: 15    Cha: 16
Hit Points      : 18 / 18      Level: 1
Exp. Points     : 0
Riblets         : 0
Ions            : 30000
Wearing Armor   : Nothing.   Armour Class: 1
Ready to Combat : NO ONE
Readied Spell   : No spell memorized.
Year A.D.       : 2000

You are carrying the following items:  (Total Weight: 0 LB's)
Nothing.
```

Values are drawn from the active player and the items registry when available,
and the command is read-only.

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
