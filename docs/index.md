# Mutants 3 System Map

Welcome to the Mutants 3 documentation portal. These pages are designed so that a new
contributor—or an AI assistant—can navigate the runtime, understand invariants, and
extend the game safely.

!!! info "How to use this map"
    Each card below links to the canonical description of a subsystem. Follow them in
    order for a code tour, or jump directly to the component you need. Architecture
    pages include problem context, inputs, outputs, invariants, failure modes, and a
    Mermaid diagram so you can reason about the data flow quickly.

## System Map

- [Quickstart](quickstart.md) — install dependencies, run the validator, and explore the
  repository layout.
- [Architecture Overview](architecture/overview.md) — layers, responsibilities, and the
  shared vocabulary for the codebase.
- [Runtime Flow](architecture/runtime.md) — how commands, services, and registries
  collaborate when a player issues a `strike`.
- [Registries](architecture/registries.md) — authoritative catalog and instance stores.
- [Items Schema](architecture/items-schema.md) — JSON shape, ranged/melee split, and
  damage floors.
- [Damage & Strike](architecture/damage-and-strike.md) — attack pipeline, armour class,
  and enchantment math.
- [Drops & Loot](architecture/drops-and-loot.md) — deterministic ordering, vaporisation
  rules, and skull spawns.
- [State Root](architecture/state-root.md) — how state is discovered on disk and how to
  override it for development.
- [Validation](architecture/validation.md) — bootstrap checks and consequences of
  invariant breaches.
- [Migrations](architecture/migrations.md) — policy for breaking changes, scripts, and
  deprecations.
- [API Reference](api/index.md) — auto-generated reference for the stable Python
  surface.
- [Guides](guides/testing.md) — practical walkthroughs for extending items, commands,
  and profiling hot paths.
- [Reference](reference/glossary.md) — glossary, CLI utilities, ADR index, and FAQ.
- [Contributing](contributing.md) — style, review expectations, and docs rules.
- [Changelog](changelog.md) — high level history of notable changes.

## Code Tour

1. Start with the [Quickstart](quickstart.md) to set up your environment and run the
   validator.
2. Read the [Architecture Overview](architecture/overview.md) for the mental model of
   registries → services → commands.
3. Dive into [Runtime](architecture/runtime.md) for an end-to-end strike walkthrough.
4. Consult [Guides](guides/extending-items.md) before changing data or behaviour.
5. Keep the [Glossary](reference/glossary.md) open for domain language while you work.
