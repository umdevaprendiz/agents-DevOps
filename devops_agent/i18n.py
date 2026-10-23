"""Translations: every text shown to the operator or sent to the model goes through t()."""
from __future__ import annotations

import locale
import os

from .locales import en, pt_br

DEFAULT_LANGUAGE = "en"
CATALOGS = {"en": en.MESSAGES, "pt-BR": pt_br.MESSAGES}
_LOCALE_ENV_VARS = ("LC_ALL", "LC_MESSAGES", "LANG")

_language = DEFAULT_LANGUAGE


def t(key: str, **values) -> str:
    """Returns the text for the current language, falling back to English."""
    template = CATALOGS[_language].get(key) or CATALOGS[DEFAULT_LANGUAGE][key]
    return template.format(**values)


def set_language(code: str | None) -> str:
    global _language
    _language = normalize(code)
    return _language


def get_language() -> str:
    return _language


def normalize(code: str | None) -> str:
    """Maps 'pt', 'pt_BR', 'pt-br' or 'Portuguese_Brazil' to 'pt-BR'; anything else to English."""
    value = (code or "").strip().lower()
    return "pt-BR" if value.startswith(("pt", "portuguese")) else DEFAULT_LANGUAGE


def detect_language(explicit: str | None = None) -> str:
    """An explicit choice (AGENT_LANGUAGE or --lang) wins; otherwise the system language decides."""
    return normalize(explicit or _system_locale())


def _system_locale() -> str:
    # The OS locale comes first: tools like Git for Windows export LANG=en_US even on Portuguese systems.
    current = locale.getlocale()[0]
    if current:
        return current
    return next((os.environ[name] for name in _LOCALE_ENV_VARS if os.environ.get(name)), "")
