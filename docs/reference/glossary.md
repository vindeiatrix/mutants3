# Glossary

| Term | Definition |
| --- | --- |
| **ADR** | Architecture Decision Record documenting intentional choices. |
| **Catalog** | Static item definitions loaded from `state/items/catalog.json`. |
| **IID** | Item Instance Identifier generated via `items_instances.mint_iid`. |
| **Instance** | Mutable item record stored in `state/items/instances.json`. |
| **State Root** | Base directory for game data resolved by `mutants.state.STATE_ROOT`. |
| **Validator** | Bootstrap step ensuring catalog and instance invariants. |
| **Drop source** | Origin tag (`bag`, `skull`, `armour`) for loot entries. |
| **Vaporised drop** | Loot that could not spawn due to ground capacity limits. |
| **Damage floor** | Minimum damage applied to bolt/innate attacks. |
| **Enchantment level** | Integer bonus applied in multiples of four to attack power. |
| **Ground cap** | Maximum number of items allowed per location (`GROUND_CAP`). |
| **Feedback bus** | Event emitter used by commands to send UI messages. |
| **Turn log** | Structured event sink for audit trails. |
