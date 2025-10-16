from __future__ import annotations

import hashlib

__all__ = ["parse_int", "derive_seed_value"]


def parse_int(value: int | str, *, base: int = 0) -> int:
    """Parse *value* into an integer.

    Parameters
    ----------
    value:
        Integer-like input. When a string is provided, the function honours the
        ``base`` argument and defaults to Python's auto-detection behaviour via
        ``int(..., 0)``.
    base:
        Radix used for parsing. ``0`` (the default) enables prefixes like
        ``0x`` for hexadecimal numbers.

    Returns
    -------
    int
        Parsed integer value.

    Raises
    ------
    ValueError
        If *value* cannot be interpreted as an integer.
    """

    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ValueError(f"Unsupported type for integer parsing: {type(value)!r}")
    try:
        return int(value.strip(), base)
    except ValueError as exc:  # pragma: no cover - defensive path
        raise ValueError(f"Invalid integer literal: {value!r}") from exc


def derive_seed_value(*parts: object, bits: int = 64) -> int:
    """Return a stable integer derived from *parts*.

    The helper joins the provided parts with ``"::"``, hashes the resulting
    string with SHA-256 and truncates the digest to the requested bit width
    (default 64 bits). The outcome is suitable for seeding ``random.Random``
    instances while remaining deterministic for identical inputs.
    """

    joined = "::".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).digest()
    width = max(8, bits // 8)
    return int.from_bytes(digest[:width], "big", signed=False)
