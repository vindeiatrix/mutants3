from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Any

def atomic_write_json(path: str | Path, data: Any) -> None:
    """
    Write JSON atomically: tmp → fsync → replace.
    Creates parent directories as needed.

    Setting ``FAST_SAVE=1`` in the environment skips the ``fsync`` call. This
    preserves the existing durable behaviour by default while still allowing
    callers (mainly fixtures/tests) to opt into a best-effort fast mode.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=p.name, dir=str(p.parent))
    fast_save = os.environ.get("FAST_SAVE", "0") == "1"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            if not fast_save:
                os.fsync(f.fileno())
        os.replace(tmp_name, p)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass

def read_json(path: str | Path, default=None):
    """
    Best-effort JSON read.
    - Returns `default` if the file is missing or malformed.
    """
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default
