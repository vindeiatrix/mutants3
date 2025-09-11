# UI Contract constants for navigation frame and direction descriptors.
#
# We lock a finite vocabulary for direction descriptors to prevent regressions.
# The renderer/formatters should only use these values (or drop/normalize).
#
COMPASS_PREFIX = "Compass: "
DIR_LINE_FMT = "{:<5} - {}"
SEPARATOR_LINE = "***"

# Ground block (header + list) and layout width
GROUND_HEADER = "On the ground lies:"
UI_WRAP_WIDTH = 80

# Canonical direction descriptors (the full set used by the original game).
DESC_AREA_CONTINUES = "area continues."
DESC_WALL_OF_ICE = "wall of ice."
DESC_ION_FORCE_FIELD = "ion force field."
DESC_OPEN_GATE = "open gate."
DESC_CLOSED_GATE = "closed gate."

# Allowed set for validation / normalization.
ALLOWED_DIR_DESCRIPTORS = {
    DESC_AREA_CONTINUES,
    DESC_WALL_OF_ICE,
    DESC_ION_FORCE_FIELD,
    DESC_OPEN_GATE,
    DESC_CLOSED_GATE,
}

__all__ = [
    "COMPASS_PREFIX",
    "DIR_LINE_FMT",
    "SEPARATOR_LINE",
    "GROUND_HEADER",
    "UI_WRAP_WIDTH",
    "DESC_AREA_CONTINUES",
    "DESC_WALL_OF_ICE",
    "DESC_ION_FORCE_FIELD",
    "DESC_OPEN_GATE",
    "DESC_CLOSED_GATE",
    "ALLOWED_DIR_DESCRIPTORS",
]
