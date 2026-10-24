"""Scenario files: loading, validation and the built-in scenarios themselves."""
import shutil

import pytest

from devops_agent import i18n
from devops_agent.evaluation import load_scenarios, select, validate
from devops_agent.evaluation.environment import Environment
from devops_agent.evaluation.scenario import Expectation, FileCheck, Pattern, ScenarioError, parse
from devops_agent.monitor import Monitor
from tests.conftest import write

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

MINIMAL = {
    "id": "demo",
    "title": {"en": "Demo", "pt-BR": "Demonstração"},
    "focus": "web",
    "files": {"docker-compose.yml": "services: {}\n"},
    "containers": [{"name": "web", "health": "unhealthy"}],
    "expect": {"diagnosis": [["8081"]]},
    "reference": {"answer": "port 8081 is wrong"},
}


def scenario(**overrides) -> dict:
    return {**MINIMAL, **overrides}


# --- Built-in scenarios --------------------------------------------------------------------------------

def test_builtin_scenarios_load_with_unique_ids_and_both_languages():
    scenarios = load_scenarios()
    assert len(scenarios) >= 5
    assert len({s.id for s in scenarios}) == len(scenarios)
    for item in scenarios:
        assert set(item.titles) == {"en", "pt-BR"}, item.id


def test_builtin_scenarios_include_a_healthy_control():
    assert any(s.expect.no_changes for s in load_scenarios())


def test_title_follows_the_language():
    item = parse(scenario(), "demo.yml")
    assert item.title == "Demo"
    i18n.set_language("pt-BR")
    assert item.title == "Demonstração"


@needs_git
def test_the_monitor_detects_exactly_the_broken_scenarios():
    for item in load_scenarios():
        with Environment(item):
            issues = Monitor(scan_logs=True).scan()
        assert bool(issues) is not item.expect.no_changes, item.id


@needs_git
def test_every_builtin_scenario_passes_its_reference_and_fails_when_nothing_is_done():
    problems = [(v.scenario.id, v.reference.error, v.reference.failed_checks()) for v in validate(load_scenarios())
                if not v.ok]
    assert problems == []


# --- Selecting -----------------------------------------------------------------------------------------

def test_select_keeps_the_requested_order_and_rejects_unknown_ids():
    scenarios = load_scenarios()
    chosen = select(scenarios, ["oom-killed", "healthcheck-port", "oom-killed"])
    assert [s.id for s in chosen] == ["oom-killed", "healthcheck-port"]
    assert select(scenarios, None) == scenarios
    with pytest.raises(ScenarioError, match="nope"):
        select(scenarios, ["nope"])


# --- Loading from a folder -------------------------------------------------------------------------------

def test_custom_folder(tmp_path):
    write(tmp_path, "b.yml", "id: second\nexpect: {no_changes: true}\nreference: {answer: fine}\n")
    write(tmp_path, "a.yaml", "id: first\nexpect: {no_changes: true}\nreference: {answer: fine}\n")
    write(tmp_path, "notes.txt", "ignored")
    assert [s.id for s in load_scenarios(tmp_path)] == ["first", "second"]


@pytest.mark.parametrize(
    "files, message",
    [
        ({}, "No scenario files"),
        ({"a.yml": "id: [unclosed"}, "invalid YAML"),
        ({"a.yml": "id: x\nexpect: {no_changes: true}\nreference: {answer: ok}\n",
          "b.yml": "id: x\nexpect: {no_changes: true}\nreference: {answer: ok}\n"}, "Duplicate"),
    ],
)
def test_folder_errors(tmp_path, files, message):
    for name, text in files.items():
        write(tmp_path, name, text)
    with pytest.raises(ScenarioError, match=message):
        load_scenarios(tmp_path)


def test_missing_folder(tmp_path):
    with pytest.raises(ScenarioError, match="not found"):
        load_scenarios(tmp_path / "missing")


# --- Validation of one scenario ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"id": None}, "missing 'id'"),
        ({"id": "Bad Id"}, "invalid id"),
        ({"colour": "red"}, "unknown field"),
        ({"expect": {}}, "'expect' needs"),
        ({"expect": {"fix": [{"a.yml": {"contains": ["x"]}}], "no_changes": True}}, "'expect' needs"),
        ({"expect": {"diagnosis": [["re:("]]}}, "invalid regular expression"),
        ({"expect": {"fix": [{"a.yml": {"has": ["x"]}}]}}, "unknown field"),
        ({"reference": {"edits": []}}, "missing 'answer'"),
        ({"containers": [{"name": "web", "state": "sleeping"}]}, "state"),
        ({"containers": "web"}, "must be a list"),
    ],
)
def test_invalid_scenarios_are_rejected_with_the_file_name(overrides, message):
    with pytest.raises(ScenarioError, match=message) as error:
        parse(scenario(**overrides), "broken.yml")
    assert "broken.yml" in str(error.value)


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "C:/Windows/x", ".git/config", "a\\b.txt", "x/../../y"])
def test_unsafe_file_paths_are_rejected(path):
    with pytest.raises(ScenarioError, match="unsafe file path"):
        parse(scenario(files={path: "x"}), "broken.yml")
    with pytest.raises(ScenarioError, match="unsafe file path"):
        parse(scenario(expect={"fix": [{path: {"contains": ["x"]}}]}), "broken.yml")


# --- Scoring rules -----------------------------------------------------------------------------------------

def test_diagnosis_patterns_ignore_case_and_support_regex():
    assert Pattern("database_url").found_in("Error: DATABASE_URL is not set", ignore_case=True)
    assert not Pattern("database_url").found_in("DATABASE_URL", ignore_case=False)
    assert Pattern(r"re:\b64\s?mb?\b").found_in("limited to 64 MB", ignore_case=True)
    assert not Pattern(r"re:\boom").found_in("the room is full", ignore_case=True)


def test_every_diagnosis_group_must_match():
    expect = Expectation(diagnosis=((Pattern("main.py"),), (Pattern("worker.py"), Pattern("worker"))))
    assert expect.diagnosed("main.py is missing; start worker.py") is True
    assert expect.diagnosed("main.py is missing") is False
    assert Expectation(no_changes=True).diagnosed("anything") is None


def test_file_checks():
    check = FileCheck("compose.yml", contains=(Pattern("localhost:80/"),), absent=(Pattern("8081"),))
    assert check.passes("test: http://localhost:80/")
    assert not check.passes("test: http://localhost:8081/ # localhost:80/")
    assert not check.passes(None)
    assert FileCheck("gone.txt", absent=(Pattern("x"),)).passes(None)


def test_any_fix_option_counts():
    option_a = (FileCheck("Dockerfile", contains=(Pattern("worker.py"),)),)
    option_b = (FileCheck("compose.yml", contains=(Pattern("worker.py"),)),)
    expect = Expectation(fix=(option_a, option_b))
    files = {"Dockerfile": "CMD main.py", "compose.yml": "command: python worker.py"}
    assert expect.fixed(files.get) is True
    assert expect.fixed({"Dockerfile": "CMD main.py"}.get) is False
    assert Expectation(no_changes=True).fixed(files.get) is None
