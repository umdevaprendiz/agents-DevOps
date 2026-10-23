"""Deciding whether a value is really a secret.

Redaction masks generously (better to hide too much). Reporting a secret must be stricter,
or every `"secret_label": "Secret files..."` or `password = os.environ[...]` becomes noise.
"""
from __future__ import annotations

import re

from ..redaction import ASSIGNMENT_RE, has_known_token, is_reference

MIN_SECRET_LENGTH = 8
_CODE_CHARS = set("(){}[]<>%")
_DOTTED_NAME_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")
_PLACEHOLDER_WORDS = ("changeme", "change_me", "example", "sample", "dummy", "placeholder", "your_", "your-", "xxx", "redacted", "<", "todo")


def plausible_secret(value: str) -> bool:
    """A literal that could be a real credential (not a reference, path, code or placeholder)."""
    value = value.strip().strip("\"'")
    if len(value) < MIN_SECRET_LENGTH or any(char.isspace() for char in value):
        return False
    if is_reference(value) or value.startswith(("/", "./", "~/")) or "://" in value:
        return False
    if _CODE_CHARS & set(value) or _DOTTED_NAME_RE.match(value):
        return False
    return not any(word in value.lower() for word in _PLACEHOLDER_WORDS)


def looks_like_secret(line: str) -> bool:
    """A well-known token format, or a sensitive key assigned a plausible literal."""
    if has_known_token(line):
        return True
    return any(plausible_secret(match.group(2)) for match in ASSIGNMENT_RE.finditer(line))
