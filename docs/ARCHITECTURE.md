### World Registry and Loading

- **Discovery:** scans `state/world/*.json` relative to the cwd.
- **Exact/nearest year:** if `<year>.json` is missing, `load_nearest_year` chooses the closest available year.
- **Fallback:** if no worlds exist, `ensure_runtime()` creates a minimal world. With `WORLD_STRICT=1`, this raises instead.
- **Observability:** `WORLD_DEBUG=1` logs discovery, requests, file paths, and chosen years.
