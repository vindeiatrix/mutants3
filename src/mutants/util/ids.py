"""Helpers for generating unique identifiers."""

from __future__ import annotations

import hashlib
import time
import uuid


def new_instance_id(*, year: int | None = None, item_id: str | None = None, tag: str | None = None) -> str:
    """Return a globally-unique, URL-safe instance identifier.

    The identifier is composed of dot-separated segments to aid debugging while
    keeping the token easy to slice when analysing logs.

    Format: ``i.<yyyymmdd>[.<year>][.<tag>][.<item_hash>].<12hex>``
    """

    yyyymmdd = time.strftime("%Y%m%d", time.gmtime())
    core = uuid.uuid4().hex[:12]
    parts = ["i", yyyymmdd]

    if year is not None:
        parts.append(str(int(year)))

    if tag:
        safe = "".join(ch for ch in tag if ch.isalnum() or ch in ("-", "_"))[:24]
        if safe:
            parts.append(safe)

    if item_id:
        digest = hashlib.blake2s(item_id.encode("utf-8"), digest_size=4).hexdigest()
        parts.append(digest)

    parts.append(core)
    return ".".join(parts)
