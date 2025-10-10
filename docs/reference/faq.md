# FAQ

## When does the validator run?

On boot, in CI, and whenever `MUTANTS_VALIDATE_CONTENT=1` is set. Disable it locally with
`MUTANTS_SKIP_VALIDATOR=1` only for temporary debugging.

## How do I repair duplicate IIDs?

Run `python tools/fix_iids.py`. The tool remints collisions and rewrites references. Always
commit the updated `instances.json` and rerun the validator.

## Can I edit JSON files directly?

No. Use the registries (`items_catalog`, `items_instances`) or provided tools. Direct edits
bypass normalisation and will fail validation.

## Where do docs live?

All documentation resides in `docs/` and is rendered via MkDocs Material. Run `make docs`
for a local preview and commit updates alongside code changes.

## How are damage floors enforced?

`commands.strike` sets bolt and innate minimums to six damage and clamps opening melee
attacks to the monster's maximum HP. See [Architecture → Damage & Strike](../architecture/damage-and-strike.md).

## What is stable vs. internal API?

The modules listed in [API Reference](../api/index.md) are considered stable. Helpers with
leading underscores (`_foo`) are internal and may change without notice.
