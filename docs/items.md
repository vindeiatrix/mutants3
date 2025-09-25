# Item Catalog

The item catalog at `state/items/catalog.json` now uses JSON booleans for
flags such as `enchantable`, `armour`, and `ranged`.  Legacy catalogs that
still contain the strings `"yes"` or `"no"` are automatically coerced to
boolean values when loaded.

See also: [utilities](utilities.md).

## Manual test fixtures

The catalog includes a handful of spawnable-but-unremarkable entries that make
manual testing easier:

* `short_sword` — basic melee weapon with `base_power_melee` 5,
  `base_power_bolt` 5, and `riblet_value`
  200 for exercising equip/look/drop flows.
* `scrap_armour` — light armour with `armour_class` 1 intended for verifying
  armour interactions after manually placing it into the armour slot inside a
  save file.
* `broken_weapon` / `broken_armour` — descriptive, non-spawnable items used to
  validate look/get/drop flows without affecting combat stats.
