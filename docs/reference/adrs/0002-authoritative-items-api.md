# ADR-0002: Authoritative Items Instances API

- **Status**: Accepted
- **Date**: 2024-05-20
- **Deciders**: @team-mutants
- **Tags**: registries, state

## Context

Historically developers edited `items/instances.json` manually. This caused duplicate IIDs,
missing enchant flags, and inconsistent positions that the runtime could not repair.

## Decision

- Treat `mutants.registries.items_instances` as the only supported persistence API.
- Enforce IID uniqueness via `STRICT_DUP_IIDS` and expose `tools/fix_iids.py` for repairs.
- Require commands and scripts to call `mint_instance`, `move_instance`, and
  `update_instance` instead of writing JSON.

## Consequences

- Registry tests protect invariants and contributors receive fast feedback.
- Manual JSON edits are forbidden; review ensures new tooling uses registry calls.
- The docs site highlights the policy so downstream tooling can integrate safely.
