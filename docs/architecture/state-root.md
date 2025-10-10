# State Root

!!! abstract "Problem"
    Runtime components and tooling must agree on where to read and write JSON state
    without hard-coding absolute paths.

!!! info "Inputs"
    - Default repository `state/` directory
    - Optional environment variable `GAME_STATE_ROOT`

!!! success "Outputs"
    - Resolved `STATE_ROOT` path exposed via `mutants.state`
    - Helper `state_path(*parts)` for composing file locations

```mermaid
flowchart LR
  ENV[GAME_STATE_ROOT env?] -->|yes| RESOLVE[_resolve_env_state_root]
  ENV -->|no| DEFAULT[default_repo_state()]
  RESOLVE --> STATE_ROOT
  DEFAULT --> STATE_ROOT
  STATE_ROOT --> PATH[state_path(*parts)]
```

## Resolution rules

- `mutants.state.default_repo_state()` walks two parents up from `state.py` and appends
  `state/`. This ensures consistent behaviour regardless of current working directory.
- When `GAME_STATE_ROOT` is set, `_resolve_env_state_root` expands `~` and resolves relative
  paths against `cwd`.
- `STATE_ROOT` is module-level, evaluated on import. Changing the environment requires a
  fresh process or explicit reload of `mutants.state`.

## Usage patterns

- Registries call `state_path("items", "catalog.json")` so overrides apply globally.
- Tests can set `GAME_STATE_ROOT` to a temporary directory to isolate fixtures.
- Tools such as `tools/fix_iids.py` respect the same root, so repairs never write to the
  wrong copy of the data.

## Failure modes

- Non-existent directories are allowed; registries create files as needed. Validation will
  still fail if required files are missing.
- Setting `GAME_STATE_ROOT` to a relative path before `os.chdir` may produce unexpected
  locations. Always set it after selecting your working directory.

## Related docs

- [Registries](registries.md)
- [Validation](validation.md)
- [Guides → Writing Commands](../guides/writing-commands.md)
