# Extending Items

This guide walks through adding or modifying catalogue entries and ensuring instances stay
consistent.

## Workflow checklist

1. **Model the change** – update `state/items/catalog.json`. Keep flags explicit and ensure
   ranged items define both base powers.
2. **Run the validator** – `python -m mutants.bootstrap.validate` to confirm no invariants
   broke.
3. **Regenerate derived data** – apply scripts when migration warnings appear (e.g.
   `python scripts/expand_item_power_fields.py`).
4. **Update loot drops** – adjust monster bag payloads or scripts if new items should drop
   automatically.
5. **Document** – add notes in `docs/changelog.md` and, if the change is architectural,
   capture it as an ADR.

## Adding a new item

```json
{
  "item_id": "plasma_whip",
  "name": "Plasma Whip",
  "spawnable": false,
  "enchantable": true,
  "ranged": false,
  "base_power_melee": 12,
  "uses_charges": false
}
```

- Always include `spawnable`. Leaving it implicit is a validation error.
- Enchanting policy forbids ranged/potion/spell-component/key/skull items from being
  enchantable. If you add such an item, set `enchantable: false` explicitly.
- If the item uses charges, set both `uses_charges` and `charges_max`.

## Updating existing instances

- Use `mutants.registries.items_instances.update_instance` inside scripts or maintenance
  commands. Pass `items_instances.REMOVE_FIELD` to delete fields safely.
- For manual repair, prefer the CLI helper in [Reference → CLI](../reference/cli.md).

## Testing changes

- Add or update fixtures under `state/` as needed.
- Extend coverage with targeted pytest cases when the item introduces new behaviour.
- Run `pytest` and `make docs` before sending a PR.

## Common pitfalls

- **Implicit enchantable** – missing `enchantable` defaults to `false` but also triggers a
  warning. Always set it explicitly.
- **Legacy base power** – keep an eye on validator warnings. Run the migration script if
  any `base_power` fields remain.
- **IID collisions** – when seeding new instances, call `items_instances.mint_instance`
  rather than editing JSON directly.

## Related docs

- [Architecture → Registries](../architecture/registries.md)
- [Architecture → Items Schema](../architecture/items-schema.md)
- [Guides → Testing](testing.md)
