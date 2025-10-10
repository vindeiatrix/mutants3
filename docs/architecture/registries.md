# Registries

!!! abstract "Problem"
    Mutants keeps state on disk under the unified state root. Registries provide the
    only supported way to read and mutate that data while enforcing invariants.

!!! info "Inputs"
    - `items/catalog.json` and `items/instances.json`
    - Optional environment variable `MUTANTS_STRICT_IIDS` for duplicate enforcement

!!! success "Outputs"
    - Normalised catalog records with explicit flags and split powers
    - Instance APIs with deterministic IID minting and collision repair story

```mermaid
flowchart LR
  CATALOG[(catalog.json)] -->|load_catalog| ItemsCatalog
  ItemsCatalog -->|require(item_id)| Services
  INSTANCES[(instances.json)] -->|load_instances| ItemsInstances
  ItemsInstances -->|mint/move/update| Services
  ItemsInstances -->|list_at| Commands
```

## Items Catalog

The catalog loader lives in [`mutants.registries.items_catalog`](../api/mutants.md#items-catalog).

- **Normalisation** – `_normalize_items` coerces numeric fields to non-negative integers,
  expands legacy `base_power` into `base_power_melee` + `base_power_bolt`, and applies
  poison defaults.
- **Enchanting policy** – `enchantable` must be an explicit boolean. Certain item families
  (ranged, spawnable, potion, spell components, key, skull) must declare `enchantable:
  false` to avoid ambiguous behaviour.
- **Spawn flag** – Every item must set `spawnable` explicitly. Validator errors include
  the offending `item_id`.
- **Ranged schema** – Items with `ranged: true` must define both `base_power_melee` and
  `base_power_bolt`. Legacy `base_power` only exists for backfills and is logged as a
  warning; the migration script `scripts/expand_item_power_fields.py` upgrades payloads.
- **API** – `ItemsCatalog.require(item_id)` raises `KeyError` for unknown IDs; use
  `list_spawnable` to filter by spawn flag.

## Items Instances

[`mutants.registries.items_instances`](../api/mutants.md#items-instances)
provides the authoritative API for live items.

- **IID policy** – `mint_iid` and `remint_iid` generate UUID4-based identifiers and cache
  them in the provided set. `STRICT_DUP_IIDS` defaults to true in CI or when
  `WORLD_DEBUG=1`. Duplicate detection logs warnings and raises when strict.
- **Normalisation** – `_normalize_instance` aligns IID fields (`iid`, `instance_id`),
  clamps enchant level (0–100), sanitises condition (1–100), and clears condition for
  broken placeholders (`broken_weapon`, `broken_armour`).
- **Authoritative methods** –
  - `mint_instance(item_id, origin)` creates and persists an instance.
  - `move_instance(iid, dest=(year, x, y))` updates positional metadata and enforces
    ground limits.
  - `update_instance(iid, **fields)` applies partial updates, removing fields when passed
    `REMOVE_FIELD` sentinel.
  - `list_instances_at(year, x, y)` returns payloads for UI consumption.
  - `charges_max_for` and `spend_charge` compute charge capacity with overrides.
- **Repair tooling** – `tools/fix_iids.py` rewrites duplicates while updating references.
  CI requires running it when `items_instances.load_instances(strict=True)` fails.

## Failure modes

- **Missing files** – Loaders fall back to legacy paths (`catalog.json`, `instances.json`).
- **Malformed JSON** – Catalog loader raises `ValueError`; instance loader returns an
  empty list and logs errors.
- **In-place edits** – Writing to JSON outside the registry bypasses normalisation and is
  forbidden. Use APIs or the CLI helper documented in [Reference → CLI](../reference/cli.md).

## Related docs

- [Items Schema](items-schema.md)
- [State Root](state-root.md)
- [Validation](validation.md)
