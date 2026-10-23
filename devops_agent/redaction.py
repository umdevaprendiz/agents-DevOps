"""Hides secrets before text reaches the model, the terminal or the audit log.

Container logs and health check outputs often carry tokens, passwords and keys,
so every tool output and every audit record goes through this module.
"""
from __future__ import annotations

import re
from typing import Any, Callable

MASK = "[REDACTED]"

_SENSITIVE_WORDS = r"password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credentials?"
_SENSITIVE_KEY_RE = re.compile(rf"(?i)[\w.-]*(?:{_SENSITIVE_WORDS})[\w.-]*")

Replacement = str | Callable[[re.Match[str]], str]


def _mask_assignment(match: re.Match[str]) -> str:
    """Keeps the key and the quotes, hides only the value: password="x" -> password="[REDACTED]"."""
    value = match.group(2)
    quote = value[0] if value[:1] in ("'", '"') else ""
    return f"{match.group(1)}{quote}{MASK}{quote}"


_RULES: tuple[tuple[re.Pattern[str], Replacement], ...] = (
    # PEM private keys (also cut ones, without the END line)
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.DOTALL), MASK),
    # user:password@host inside URLs (postgres://, redis://, https://...)
    (re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]+:)[^\s@/]+(@)"), rf"\1{MASK}\2"),
    # Authorization headers
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/-]{8,}=*"), rf"\1 {MASK}"),
    # Well-known token formats
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), MASK),  # AWS access key id
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), MASK),  # GitHub token
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), MASK),  # GitHub fine-grained token
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), MASK),  # GitLab token
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"), MASK),  # Slack token
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), MASK),  # OpenAI-style API key
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), MASK),  # Google API key
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"), MASK),  # Telegram bot token
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), MASK),  # JWT
    # key=value, key: value and "key": "value" when the key looks sensitive
    (
        re.compile(rf"(?i)(\b[\w.-]*(?:{_SENSITIVE_WORDS})[\w.-]*[\"']?\s*[:=]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s\"',;&]+)"),
        _mask_assignment,
    ),
)


def redact(text: str) -> str:
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


def redact_data(value: Any) -> Any:
    """Redacts strings inside dicts and lists; values under sensitive keys are hidden entirely."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redact_entry(key, item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_data(item) for item in value]
    return value


def _redact_entry(key: Any, value: Any) -> Any:
    if isinstance(key, str) and _SENSITIVE_KEY_RE.fullmatch(key) and value not in (None, ""):
        return MASK
    return redact_data(value)
