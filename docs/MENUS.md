# Menus

## Class Selection

The game boots into the class selection screen. Layout mirrors the classic BBS
style:

```
1. Mutant Thief     Level: 1   Year: 2000   (0  0)
2. Mutant Priest    Level: 1   Year: 2000   (0  0)
3. Mutant Wizard    Level: 1   Year: 2000   (0  0)
4. Mutant Warrior   Level: 1   Year: 2000   (0  0)
5. Mutant Mage      Level: 1   Year: 2000   (0  0)
Type BURY [class number] to reset a player.
***
Select (Bury, 1–5, ?)
```

- Press `1`–`5` to activate a class and enter the in-game view.
- Type `?` for a reminder: “Enter 1–5 to choose a class; ‘Bury’ resets later.”
- `BURY <n>` is accepted but currently responds with “Bury not implemented yet.”
- Type `quit`/`q` to save and exit immediately.

The menu always follows the template order regardless of the current active
class.

## In-Game

- `statistics`/`sta` prints a summary for the active player.
- Press `x` at any time to save and return to the class selection menu.
- Other legacy commands (movement, look, etc.) continue to work while we migrate
  the rest of the UI.
