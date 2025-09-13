## [Unreleased]
### Added
- World-load diagnostics:
  - `WORLD_DEBUG` env flag for detailed logs.
  - `WORLD_STRICT` env flag to fail on missing world JSONs.
- Logs for discovery, world loading, nearest-year fallback, and minimal world creation.
- Command: `open <dir>` reopens a closed gate.
- Documentation:
  - README troubleshooting section.
  - ARCHITECTURE notes on cwd dependence and fallback.
  - New `docs/LOGGING.md`.

### Fixed
- CLOSE [direction] now detects gates by type and closes open gates.
- Closed or locked gates now block movement; attempting to walk into one shows
  "The {dir} gate is closed."
- Debug add-item now validates against state/items/catalog.json; unknown or
  ambiguous names are rejected with suggestions.
