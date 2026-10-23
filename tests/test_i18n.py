import re
import string
from pathlib import Path

import pytest

from devops_agent import i18n
from devops_agent.locales import en, pt_br

PACKAGE = Path(i18n.__file__).parent
SOURCES = {path: path.read_text(encoding="utf-8") for path in PACKAGE.rglob("*.py") if "locales" not in path.parts}


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


# --- Catalogs ------------------------------------------------------------------------------------

def test_catalogs_have_the_same_keys():
    assert set(en.MESSAGES) == set(pt_br.MESSAGES)


@pytest.mark.parametrize("key", sorted(en.MESSAGES))
def test_translations_use_the_same_placeholders(key):
    assert _fields(en.MESSAGES[key]) == _fields(pt_br.MESSAGES[key])


def test_every_key_used_in_the_code_exists():
    used = set()
    for source in SOURCES.values():
        used |= set(re.findall(r"""\bt\(\s*["']([\w.]+)["']""", source))
    assert used
    assert used <= set(en.MESSAGES)


def test_every_catalog_key_is_used_somewhere():
    code = "\n".join(SOURCES.values())
    unused = [key for key in en.MESSAGES if f'"{key}"' not in code and f"'{key}'" not in code]
    assert unused == []


# --- Language selection ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "code, expected",
    [
        ("pt", "pt-BR"),
        ("pt_BR", "pt-BR"),
        ("pt-br", "pt-BR"),
        ("Portuguese_Brazil", "pt-BR"),
        ("en_US", "en"),
        ("fr", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_normalize(code, expected):
    assert i18n.normalize(code) == expected


def test_explicit_choice_wins_over_the_system(monkeypatch):
    monkeypatch.setattr(i18n, "_system_locale", lambda: "pt_BR")
    assert i18n.detect_language("en") == "en"
    assert i18n.detect_language(None) == "pt-BR"


def test_system_locale_comes_before_lang_variable(monkeypatch):
    # Git for Windows exports LANG=en_US even when the OS is in Portuguese.
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: ("pt_BR", "cp1252"))
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.detect_language() == "pt-BR"


def test_lang_variable_is_the_fallback(monkeypatch):
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: (None, None))
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    assert i18n.detect_language() == "pt-BR"


# --- t() ---------------------------------------------------------------------------------------------

def test_t_formats_placeholders():
    assert i18n.t("cli.problems_found", count=3) == "3 container(s) with problems."


def test_t_falls_back_to_english_when_a_translation_is_missing(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS, "pt-BR", {})
    i18n.set_language("pt-BR")
    assert i18n.t("cli.stopped") == "stopped"
