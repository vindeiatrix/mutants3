# Writing Commands

Command modules live under `mutants.commands`. They coordinate registries, services, and
UI buses. Follow these guidelines to keep behaviour deterministic and testable.

## Principles

1. **Registries first** – never mutate JSON directly. Use `items_instances` and related
   registries for all persistence.
2. **Services for business logic** – combat math lives in `services.damage_engine` and
   `services.combat_calc`; loot logic lives in `services.combat_loot`.
3. **Emit structured events** – push to `feedback_bus` for user-visible messages and to
   `turnlog.emit` for audit trails.
4. **Handle missing data** – defensive checks guard against absent monsters, catalog files,
   or wielded weapons.

## Template

```python
from typing import Any, Mapping
from mutants.registries import items_catalog, items_instances
from mutants.services import damage_engine


def my_command(arg: str, ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    bus = ctx["feedback_bus"]
    catalog = items_catalog.load_catalog()
    instances = items_instances.load_instances()
    # orchestrate services, push events, return summary
    return {"ok": True}
```

## Strike as exemplar

- Resolves targets through `player_state` and monster registry.
- Delegates combat to `damage_engine.resolve_attack`.
- Applies minimum damage floors and weapon wear before mutating state.
- Drops loot via `combat_loot.drop_monster_loot`, respecting ground capacity.
- Emits `COMBAT/HIT` and `COMBAT/KILL` events plus structured turn log entries.

## Testing commands

- Use pytest fixtures to stub buses and registries. The tests under `tests/commands/`
  provide examples of asserting event streams.
- Validate invariants by asserting no direct file writes occur; use monkeypatching to track
  registry calls when necessary.
- When adding new commands, document them in [Reference → FAQ](../reference/faq.md).

## Related docs

- [Architecture → Runtime Flow](../architecture/runtime.md)
- [Architecture → Damage & Strike](../architecture/damage-and-strike.md)
- [Guides → Testing](testing.md)
