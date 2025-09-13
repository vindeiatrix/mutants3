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
