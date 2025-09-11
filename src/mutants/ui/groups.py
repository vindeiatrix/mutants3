# Minimal, stable registry of UI color groups.
#
# Each rendered text fragment should declare ONE group. The renderer/styles
# resolve the group -> color via state/ui/colors.json (or theme override).
#
# Groups use dotted keys for hierarchical fallback (e.g., "compass.line"
# also matches "compass.*" if configured).
#
COMPASS_LINE = "compass.line"
ROOM_TITLE = "room.title"
ROOM_DESC = "room.desc"
DIR_OPEN = "dir.open"
DIR_BLOCKED = "dir.blocked"
HEADER = "header"
FOOTER = "footer"
FEEDBACK_INFO = "feedback.info"
FEEDBACK_WARN = "feedback.warn"
FEEDBACK_ERR = "feedback.err"
LOG_LINE = "log.line"

__all__ = [
    "COMPASS_LINE",
    "ROOM_TITLE",
    "ROOM_DESC",
    "DIR_OPEN",
    "DIR_BLOCKED",
    "HEADER",
    "FOOTER",
    "FEEDBACK_INFO",
    "FEEDBACK_WARN",
    "FEEDBACK_ERR",
    "LOG_LINE",
]
