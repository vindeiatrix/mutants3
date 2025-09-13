# Item Catalog

The item catalog at `state/items/catalog.json` now uses JSON booleans for
flags such as `enchantable`, `armour`, and `ranged`.  Legacy catalogs that
still contain the strings `"yes"` or `"no"` are automatically coerced to
boolean values when loaded.
