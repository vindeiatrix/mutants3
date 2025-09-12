import re

_NO_BREAK_HYPHEN = "\u2011"  # U+2011
_NBSP = "\u00A0"             # U+00A0

_ARTICLE_RE = re.compile(r"^(A|An) ")

def harden_final_display(s: str) -> str:
    """Apply non-breaking rules to a final display string.

    - Replace ASCII '-' with U+2011 no-break hyphen.
    - Bind leading article (A/An) to next token with U+00A0.
    """
    if not s:
        return s
    s = s.replace("-", _NO_BREAK_HYPHEN)
    s = _ARTICLE_RE.sub(lambda m: f"{m.group(1)}{_NBSP}", s)
    return s
