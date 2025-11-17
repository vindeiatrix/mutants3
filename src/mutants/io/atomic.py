from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Any, Callable

def atomic_write_json(
    path: str | Path,
    data: Any,
    *,
    on_error: Callable[[Path, str | None, BaseException], None] | None = None,
) -> None:
    """
    Write JSON atomically: tmp → fsync → replace.
    Creates parent directories as needed.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = -1
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=p.name, dir=str(p.parent))
    except Exception as exc:
        if on_error is not None:
            try:
                on_error(p, tmp_name, exc)
            except Exception:
                pass
        raise
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, p)
    except Exception as exc:
        if on_error is not None:
            try:
                on_error(p, tmp_name, exc)
            except Exception:
                pass
        raise
    finally:
        try:
            if tmp_name and os.path.exists(tmp_name):
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
