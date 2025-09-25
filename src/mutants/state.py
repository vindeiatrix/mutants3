"""Helpers for resolving the on-disk state directory."""

from __future__ import annotations

import os
from pathlib import Path


def default_repo_state() -> Path:
    """Return the default path to the bundled ``state`` directory.

    This anchors relative to the project repository instead of the current
    working directory so tooling and runtime environments agree on the same
    location by default.
    """

    return Path(__file__).resolve().parents[2] / "state"


def _resolve_env_state_root(raw: str) -> Path:
    """Return the state root specified via the ``GAME_STATE_ROOT`` env var."""

    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


_STATE_ROOT_ENV = os.getenv("GAME_STATE_ROOT")
if _STATE_ROOT_ENV:
    STATE_ROOT = _resolve_env_state_root(_STATE_ROOT_ENV)
else:
    STATE_ROOT = default_repo_state()


def state_path(*parts: os.PathLike[str] | str) -> Path:
    """Join ``parts`` onto :data:`STATE_ROOT` as a :class:`pathlib.Path`."""

    return STATE_ROOT.joinpath(*parts)
