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

    On Windows the final ``os.replace`` can raise ``PermissionError`` if the
    destination file is momentarily locked by another process.  Falling back to
    a direct write keeps progress from being lost (rather than surfacing as an
    autosave failure and leaving the old state on disk).
    Creates parent directories as needed.
    """

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Pre-encode once so we can re-use the payload for fallback writes.
    payload = json.dumps(data, ensure_ascii=False, indent=2)

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
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())

        def _notify(error: BaseException) -> None:
            if on_error is not None:
                try:
                    on_error(p, tmp_name, error)
                except Exception:
                    pass

        try:
            os.replace(tmp_name, p)
            return
        except PermissionError as exc:
            # Windows can refuse to replace when another handle is open.  Try
            # to clear basic attributes and attempt again before resorting to a
            # non-atomic direct write.
            try:
                if p.exists():
                    try:
                        os.chmod(p, 0o666)
                    except Exception:
                        pass
                    os.replace(tmp_name, p)
                    return
            except PermissionError:
                # Final fallback: write directly to the destination so state
                # is still persisted, even if not atomically.
                try:
                    with p.open("w", encoding="utf-8") as direct:
                        direct.write(payload)
                        direct.flush()
                        os.fsync(direct.fileno())
                    return
                except Exception as inner_exc:  # pragma: no cover - best effort
                    _notify(inner_exc)
                    raise inner_exc from exc
            except Exception as inner_exc:
                _notify(inner_exc)
                raise
            # If the chmod/replace path failed without raising, fall through
            # and surface the original PermissionError.
            _notify(exc)
            raise
        except Exception as exc:
            _notify(exc)
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
