#!/usr/bin/env python3
"""
Guard: fail if hyphen splitting is detected in UI wrap diagnostics.

Looks for:
- Explicit probe result 'UI/WRAP/BAD_SPLIT'
- Any diagnostic line (UI/PROBE or UI/GROUND) with a dangling '-' at end of a wrapped diagnostic line.
"""

import sys, re, pathlib

LOG = pathlib.Path("state/logs/game.log")
if not LOG.exists():
    print("No log file found at state/logs/game.log; ensure the game was run once.", file=sys.stderr)
    sys.exit(2)

txt = LOG.read_text(encoding="utf-8", errors="replace")
lines = txt.splitlines()

# 1) Hard fail if the probe flagged a bad split
if any("UI/WRAP/BAD_SPLIT" in l for l in lines):
    print("❌ Detected UI/WRAP/BAD_SPLIT in diagnostics. Hyphen wrap regression.", file=sys.stderr)
    sys.exit(1)

# 2) Scan only our diagnostic payload lines for dangling hyphen at EOL
diag = [l for l in lines if ("UI/PROBE" in l or "UI/GROUND" in l)]
dangling_hyphen = any(re.search(r'-"\s*$', l) for l in diag)  # conservative check

if dangling_hyphen:
    print("❌ Detected dangling '-' at end of diagnostic line payload. Hyphen wrap regression.", file=sys.stderr)
    sys.exit(1)

# Optionally require at least one OK probe
ok = any("UI/WRAP/OK" in l for l in lines)
if not ok:
    print("⚠️ No probe result found. Did you run the probe? (This is not a failure by itself.)")

print("✅ Wrap guard passed.")
