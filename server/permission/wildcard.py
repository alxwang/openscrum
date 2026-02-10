"""
Wildcard pattern matching (ref: opencode util/wildcard.ts).

* matches any sequence, ? matches single character.
Special regex chars in pattern are escaped.
"""

import re
from typing import Any


def match(text: str, pattern: str) -> bool:
    """
    Return True if text matches pattern.
    * -> .* , ? -> . , other regex metachars escaped.
    """
    # Escape regex special chars except * and ?
    escaped = re.escape(pattern)
    # Restore * and ? as wildcards (re.escape turns them into \\* and \\?)
    escaped = escaped.replace(r"\*", ".*").replace(r"\?", ".")
    # If pattern ends with " *" (space + star), make trailing part optional
    if escaped.endswith(r" \.*"):
        escaped = escaped[: -4] + r"( .*)?"
    return bool(re.fullmatch(escaped, text, re.DOTALL))


def all_match(text: str, patterns: dict[str, Any]) -> Any:
    """
    Find first matching pattern (by key) and return its value.
    Keys sorted by length ascending then lexicographically.
    """
    for key in sorted(patterns.keys(), key=lambda k: (len(k), k)):
        if match(text, key):
            return patterns[key]
    return None
