import re
import unicodedata

_ARTICLES = {"a", "an", "the"}

def normalize_item_query(s: str | None) -> str:
    """
    Normalize a user-entered item query into a canonical, hyphenated token.
    Examples:
      '  "A  Nuclear–Thong"  ' -> 'nuclear-thong'
      "the Nuclear Thong"      -> 'nuclear-thong'
      "NUCLEAR-TH"             -> 'nuclear-th'
    """
    if not s:
        return ""
    # Unicode normalize (turn “smart” punctuation into consistent forms)
    s = unicodedata.normalize("NFKC", s)
    # Trim whitespace and outer quotes (including Unicode quotes)
    s = s.strip()
    s = s.strip("'\"“”‘’")
    s = s.strip()
    # Lowercase
    s = s.lower()
    # Drop leading articles
    parts = s.split()
    if parts and parts[0] in _ARTICLES:
        parts = parts[1:]
    s = " ".join(parts)
    # Replace any non-alnum run with a single hyphen; trim edge hyphens
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s
