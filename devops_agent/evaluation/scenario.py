"""Evaluation scenarios: a project with a known bug (or none), the containers Docker would report,
what a good answer must contain and a reference solution.

Scenarios are YAML files. The built-in ones live in scenarios/; `eval --scenarios DIR` loads others.
Patterns are plain text, or a regular expression when they start with "re:".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Callable

import yaml

from ..i18n import get_language, t
from .simulator import ContainerSpec, SimulationError

REGEX_PREFIX = "re:"
SCENARIO_SUFFIXES = (".yml", ".yaml")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SCENARIO_FIELDS = {"id", "title", "focus", "files", "containers", "expect", "reference"}
EXPECT_FIELDS = {"diagnosis", "fix", "no_changes"}
CHECK_FIELDS = {"contains", "absent"}
REFERENCE_FIELDS = {"title", "answer", "edits"}


class ScenarioError(Exception):
    """A scenario file that cannot be loaded."""


# --- Patterns and checks -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Pattern:
    text: str

    @property
    def regex(self) -> str | None:
        return self.text[len(REGEX_PREFIX):] if self.text.startswith(REGEX_PREFIX) else None

    def found_in(self, content: str, ignore_case: bool) -> bool:
        if self.regex is not None:
            flags = re.MULTILINE | (re.IGNORECASE if ignore_case else 0)
            return re.search(self.regex, content, flags) is not None
        return self.text.casefold() in content.casefold() if ignore_case else self.text in content


@dataclass(frozen=True)
class FileCheck:
    """A file after the proposals are applied: must contain every `contains` and none of `absent`."""

    path: str
    contains: tuple[Pattern, ...] = ()
    absent: tuple[Pattern, ...] = ()

    def passes(self, content: str | None) -> bool:
        if content is None:
            return not self.contains
        has_all = all(pattern.found_in(content, ignore_case=False) for pattern in self.contains)
        return has_all and not any(pattern.found_in(content, ignore_case=False) for pattern in self.absent)


@dataclass(frozen=True)
class Expectation:
    # Every group must appear in the answer; a group matches when any of its patterns does (any case).
    diagnosis: tuple[tuple[Pattern, ...], ...] = ()
    # Any option counts as fixed; an option passes when all of its file checks do.
    fix: tuple[tuple[FileCheck, ...], ...] = ()
    # A healthy scenario: the agent must not propose anything.
    no_changes: bool = False

    def diagnosed(self, text: str) -> bool | None:
        if not self.diagnosis:
            return None
        return all(any(pattern.found_in(text, ignore_case=True) for pattern in group) for group in self.diagnosis)

    def fixed(self, read: Callable[[str], str | None]) -> bool | None:
        if not self.fix:
            return None
        return any(all(check.passes(read(check.path)) for check in option) for option in self.fix)


@dataclass(frozen=True)
class Reference:
    """What a perfect agent would answer and propose (`eval --validate` checks it passes)."""

    answer: str
    title: str = ""
    edits: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Scenario:
    id: str
    titles: dict[str, str]
    focus: str
    files: dict[str, str]
    containers: tuple[ContainerSpec, ...]
    expect: Expectation
    reference: Reference

    @property
    def title(self) -> str:
        return self.titles.get(get_language()) or self.titles.get("en") or next(iter(self.titles.values()), self.id)


# --- Loading -------------------------------------------------------------------------------------------

def load_scenarios(folder: str | Path | None = None) -> list[Scenario]:
    """Built-in scenarios, or every *.yml file of a folder, sorted by file name."""
    source = Path(folder) if folder else resources.files(__package__).joinpath("scenarios")
    if not source.is_dir():
        raise ScenarioError(t("eval.error.folder", folder=str(source)))
    files = sorted((item for item in source.iterdir() if item.name.endswith(SCENARIO_SUFFIXES)), key=lambda f: f.name)
    if not files:
        raise ScenarioError(t("eval.error.no_scenarios", folder=str(source)))
    scenarios = [load_file(item) for item in files]
    _check_unique(scenarios)
    return scenarios


def load_file(path) -> Scenario:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ScenarioError(t("eval.error.yaml", source=path.name, error=error)) from error
    return parse(data, path.name)


def select(scenarios: list[Scenario], ids: list[str] | None) -> list[Scenario]:
    """Keeps the requested scenarios, in the order they were asked for."""
    if not ids:
        return scenarios
    by_id = {scenario.id: scenario for scenario in scenarios}
    unknown = [item for item in ids if item not in by_id]
    if unknown:
        raise ScenarioError(t("eval.error.unknown_scenario", ids=", ".join(unknown), available=", ".join(by_id)))
    return [by_id[item] for item in dict.fromkeys(ids)]


def _check_unique(scenarios: list[Scenario]) -> None:
    seen: set[str] = set()
    for scenario in scenarios:
        if scenario.id in seen:
            raise ScenarioError(t("eval.error.duplicate", id=scenario.id))
        seen.add(scenario.id)


# --- Parsing -------------------------------------------------------------------------------------------

def parse(data, source: str) -> Scenario:
    raw = _mapping(data, source, "scenario", SCENARIO_FIELDS)
    scenario_id = _required(raw, source, "id")
    if not isinstance(scenario_id, str) or not ID_RE.match(scenario_id):
        raise ScenarioError(t("eval.error.id", source=source, id=scenario_id))
    return Scenario(
        id=scenario_id,
        titles=_titles(raw.get("title"), source),
        focus=str(raw.get("focus") or ""),
        files=_files(raw.get("files") or {}, source),
        containers=_containers(raw.get("containers") or [], source),
        expect=_expectation(_required(raw, source, "expect"), source),
        reference=_reference(_required(raw, source, "reference"), source),
    )


def _mapping(value, source: str, where: str, allowed: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ScenarioError(t("eval.error.type", source=source, field=where, expected="mapping"))
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ScenarioError(t("eval.error.unknown_fields", source=source, where=where, fields=", ".join(unknown)))
    return value


def _dict(value, source: str, where: str) -> dict:
    """A mapping with free keys (file paths)."""
    if not isinstance(value, dict):
        raise ScenarioError(t("eval.error.type", source=source, field=where, expected="mapping"))
    return value


def _required(raw: dict, source: str, name: str):
    if raw.get(name) in (None, ""):
        raise ScenarioError(t("eval.error.missing", source=source, field=name))
    return raw[name]


def _list(value, source: str, where: str) -> list:
    if not isinstance(value, list):
        raise ScenarioError(t("eval.error.type", source=source, field=where, expected="list"))
    return value


def _titles(value, source: str) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, str):
        return {"en": value}
    return {str(language): str(text) for language, text in _mapping(value, source, "title", {"en", "pt-BR"}).items()}


def _files(value, source: str) -> dict[str, str]:
    return {_safe_path(path, source): str(content) for path, content in _dict(value, source, "files").items()}


def _safe_path(path, source: str) -> str:
    """Relative paths inside the scenario folder only: no absolute paths, '..' or .git."""
    text = str(path)
    parts = PurePosixPath(text).parts
    if not text or "\\" in text or ":" in text or text.startswith("/") or ".." in parts or ".git" in parts:
        raise ScenarioError(t("eval.error.path", source=source, path=text))
    return PurePosixPath(text).as_posix()


def _containers(value, source: str) -> tuple[ContainerSpec, ...]:
    try:
        return tuple(ContainerSpec.from_dict(item) for item in _list(value, source, "containers"))
    except (SimulationError, TypeError) as error:
        raise ScenarioError(f"{source}: {error}") from error


def _expectation(value, source: str) -> Expectation:
    raw = _mapping(value, source, "expect", EXPECT_FIELDS)
    diagnosis = _list(raw.get("diagnosis") or [], source, "expect.diagnosis")
    groups = tuple(_patterns(group, source, "expect.diagnosis") for group in diagnosis)
    fix = tuple(_fix_option(option, source) for option in _list(raw.get("fix") or [], source, "expect.fix"))
    no_changes = bool(raw.get("no_changes"))
    if not (groups or fix or no_changes) or (fix and no_changes):
        raise ScenarioError(t("eval.error.expectation", source=source))
    return Expectation(diagnosis=groups, fix=fix, no_changes=no_changes)


def _fix_option(value, source: str) -> tuple[FileCheck, ...]:
    files = _dict(value, source, "expect.fix")
    if not files:
        raise ScenarioError(t("eval.error.type", source=source, field="expect.fix", expected="mapping"))
    return tuple(_file_check(path, check, source) for path, check in files.items())


def _file_check(path, value, source: str) -> FileCheck:
    raw = _mapping(value, source, f"expect.fix.{path}", CHECK_FIELDS)
    contains = _patterns(raw.get("contains") or [], source, f"expect.fix.{path}.contains")
    absent = _patterns(raw.get("absent") or [], source, f"expect.fix.{path}.absent")
    return FileCheck(_safe_path(path, source), contains, absent)


def _patterns(value, source: str, where: str) -> tuple[Pattern, ...]:
    items = [value] if isinstance(value, str) else _list(value, source, where)
    patterns = tuple(Pattern(str(item)) for item in items)
    for pattern in patterns:
        _check_regex(pattern, source)
    return patterns


def _check_regex(pattern: Pattern, source: str) -> None:
    if pattern.regex is None:
        return
    try:
        re.compile(pattern.regex)
    except re.error as error:
        raise ScenarioError(t("eval.error.regex", source=source, pattern=pattern.text, error=error)) from error


def _reference(value, source: str) -> Reference:
    raw = _mapping(value, source, "reference", REFERENCE_FIELDS)
    edits = tuple(_mapping(edit, source, "reference.edits", {"path", "old_text", "new_text"})
                  for edit in _list(raw.get("edits") or [], source, "reference.edits"))
    return Reference(answer=str(_required(raw, source, "answer")), title=str(raw.get("title") or ""), edits=edits)
