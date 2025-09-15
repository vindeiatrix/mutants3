## [Unreleased]
### Added
- World-load diagnostics:
  - `WORLD_DEBUG` env flag for detailed logs.
  - `WORLD_STRICT` env flag to fail on missing world JSONs.
- Logs for discovery, world loading, nearest-year fallback, and minimal world creation.
- Command: `open <dir>` reopens a closed gate.
- Item token normalization helper for consistent item parsing.
- Debug add item supports fuzzy matching.
- Class Selection startup screen, statistics command with prefix matching, and
  save-game foundation (schema v1, Bury stubbed for now).
- Documentation:
  - README troubleshooting section.
  - ARCHITECTURE notes on cwd dependence and fallback.
  - New `docs/LOGGING.md`.
### Changed
- Throw command drops the item at your feet if the direction is blocked.
- Item catalog coerces legacy `"yes"`/`"no"` flags to booleans.
- Player save data accepts both `"armor"` and `"armour"` spellings.

### Fixed
- CLOSE [direction] now detects gates by type and closes open gates.
- Closed or locked gates now block movement; attempting to walk into one shows
  "The {dir} gate is closed."
