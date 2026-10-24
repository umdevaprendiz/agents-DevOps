"""Running and scoring: real Agent and Team with scripted models, in a throwaway environment."""
import json
import shutil

import pytest
from rich.console import Console

from devops_agent import docker_tools as dk
from devops_agent.agent import Agent
from devops_agent.config import Config
from devops_agent.evaluation import EventLog, as_json, deny_actions, evaluate, run_scenario, summarize
from devops_agent.evaluation.environment import Environment
from devops_agent.evaluation.results import RunResult, Tally, by_scenario, tally
from devops_agent.evaluation.scenario import parse
from devops_agent.pipeline import Team
from tests.conftest import FakeClient, assistant

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

COMPOSE = (
    "services:\n"
    "  web:\n"
    "    image: nginx:1.27-alpine\n"
    "    healthcheck:\n"
    '      test: ["CMD", "wget", "-qO-", "http://localhost:8081/"]\n'
)
PORT_FIX = {"path": "docker-compose.yml", "old_text": "localhost:8081", "new_text": "localhost:80"}
BROKEN = {
    "id": "port",
    "focus": "web",
    "files": {"docker-compose.yml": COMPOSE},
    "containers": [{"name": "web", "health": "unhealthy", "health_log": ["connection refused"]}],
    "expect": {"diagnosis": [["8081"]], "fix": [{"docker-compose.yml": {"contains": ["localhost:80/"], "absent": ["8081"]}}]},
    "reference": {"answer": "the healthcheck calls 8081", "edits": [PORT_FIX]},
}
HEALTHY = {
    "id": "fine",
    "files": {"docker-compose.yml": COMPOSE.replace("8081", "80")},
    "containers": [{"name": "web", "health": "healthy"}],
    "expect": {"no_changes": True},
    "reference": {"answer": "all good"},
}


@pytest.fixture(autouse=True)
def no_real_docker(monkeypatch):
    def refuse(*args):
        raise AssertionError("the real docker CLI was called")

    monkeypatch.setattr(dk, "_docker_cli", refuse)


def scripted_agent(*replies):
    """A team factory: one real Agent whose model answers with the scripted replies."""
    clients = []

    def make(scenario, tools, events, on_brief):
        agent = Agent(Config(), Console(quiet=True), deny_actions, events, tools=tools)
        agent.client = FakeClient(*replies)
        clients.append(agent.client)
        return Team(agent)

    make.clients = clients
    return make


def propose(*edits, title="Fix the healthcheck port"):
    return ("propose_change", {"title": title, "explanation": "nginx listens on 80", "edits": list(edits)})


# --- One run ---------------------------------------------------------------------------------------------

def test_a_correct_agent_passes_and_its_steps_are_counted():
    make = scripted_agent(
        assistant(calls=[("collect_diagnostics", {})]),
        assistant(calls=[("inspect_container", {"container": "web"})]),
        assistant(calls=[propose(PORT_FIX)]),
        assistant("**Cause:** the healthcheck calls port 8081 but nginx listens on 80."),
    )
    result = run_scenario(parse(BROKEN, "port.yml"), make)

    assert (result.diagnosis, result.fix, result.passed) == (True, True, True)
    assert (result.tool_calls, result.tool_errors, result.proposals) == (3, 0, 1)
    assert "collect_diagnostics" in str(make.clients[0].calls[0]["messages"])  # the /debug task was sent


def test_the_agent_sees_the_simulated_containers():
    make = scripted_agent(assistant(calls=[("collect_diagnostics", {})]), assistant("done"))
    run_scenario(parse(BROKEN, "port.yml"), make)
    tool_message = make.clients[0].calls[1]["messages"][-1]
    assert "web: healthcheck failing" in tool_message["content"]


def test_a_wrong_diagnosis_and_no_fix_fail():
    make = scripted_agent(assistant(calls=[("list_containers", {})]), assistant("Probably a network problem."))
    result = run_scenario(parse(BROKEN, "port.yml"), make)
    assert (result.diagnosis, result.fix, result.passed) == (False, False, False)
    assert result.failed_checks() == ["diagnosis", "fix"]


def test_the_cause_may_be_in_the_proposal_explanation():
    make = scripted_agent(assistant(calls=[propose(PORT_FIX, title="Healthcheck uses 8081")]), assistant("Fixed."))
    assert run_scenario(parse(BROKEN, "port.yml"), make).diagnosis is True


def test_a_fix_that_changes_the_wrong_thing_fails():
    wrong = {"path": "docker-compose.yml", "old_text": "nginx:1.27-alpine", "new_text": "nginx:1.27"}
    make = scripted_agent(assistant(calls=[propose(wrong)]), assistant("port 8081 is wrong"))
    result = run_scenario(parse(BROKEN, "port.yml"), make)
    assert (result.diagnosis, result.fix) == (True, False)


def test_container_actions_are_denied_and_counted():
    make = scripted_agent(assistant(calls=[("restart_container", {"container": "web"})]), assistant("port 8081"))
    result = run_scenario(parse(BROKEN, "port.yml"), make)
    assert result.denied == 1


def test_conflicting_proposals_do_not_break_the_scoring():
    other = {"path": "docker-compose.yml", "old_text": "localhost:8081", "new_text": "localhost:9999"}
    make = scripted_agent(assistant(calls=[propose(PORT_FIX), propose(other)]), assistant("port 8081"))
    result = run_scenario(parse(BROKEN, "port.yml"), make)
    assert result.proposals == 2 and result.fix is True  # the first one merged, the second conflicted


def test_proposing_changes_in_a_healthy_scenario_fails():
    change = {"path": "docker-compose.yml", "old_text": "nginx:1.27-alpine", "new_text": "nginx:1.27.2-alpine"}
    make = scripted_agent(assistant(calls=[propose(change)]), assistant("pinned the image"))
    result = run_scenario(parse(HEALTHY, "fine.yml"), make)
    assert (result.no_changes, result.passed) == (False, False)


def test_doing_nothing_passes_a_healthy_scenario():
    make = scripted_agent(assistant(calls=[("collect_diagnostics", {})]), assistant("Everything is healthy."))
    result = run_scenario(parse(HEALTHY, "fine.yml"), make)
    assert (result.no_changes, result.diagnosis, result.fix, result.passed) == (True, None, None, True)


def test_model_errors_are_recorded_not_raised():
    make = scripted_agent(ConnectionError("ollama is down"))
    result = run_scenario(parse(BROKEN, "port.yml"), make)
    assert result.error == "ollama is down" and result.passed is False


def test_the_analyst_report_is_scored_separately():
    class Fixed:
        def __init__(self, answer):
            self.answer = answer

        def run(self, task, require_evidence=False):
            return self.answer

        def reset(self):
            pass

    def make(scenario, tools, events, on_brief):
        return Team(Fixed("network problem"), Fixed("## Evidence\nhealthcheck calls 8081"), on_brief=on_brief)

    result = run_scenario(parse(BROKEN, "port.yml"), make)
    assert (result.analyst, result.diagnosis) == (True, False)


def test_the_environment_is_removed_and_docker_restored():
    with Environment(parse(BROKEN, "port.yml")) as env:
        root = env.root
        assert (root / "docker-compose.yml").read_bytes() == COMPOSE.encode()
        assert dk._BACKEND.get() is env.docker
    assert not root.exists()
    assert dk._BACKEND.get() is None


# --- Several runs ----------------------------------------------------------------------------------------

def test_evaluate_repeats_and_reports_progress():
    started, finished = [], []

    class Progress:
        def __init__(self, scenario, attempt):
            started.append((scenario.id, attempt))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def make(scenario, tools, events, on_brief):
        return Team(_Answer("nothing found"))

    scenarios = [parse(BROKEN, "port.yml"), parse(HEALTHY, "fine.yml")]
    results = evaluate(scenarios, make, repeat=2, progress=Progress, on_result=finished.append)

    assert started == [("port", 1), ("port", 2), ("fine", 1), ("fine", 2)]
    assert [(r.scenario, r.attempt, r.passed) for r in finished] == [
        ("port", 1, False), ("port", 2, False), ("fine", 1, True), ("fine", 2, True)]
    assert len(results) == 4


class _Answer:
    def __init__(self, text):
        self.text = text

    def run(self, task, require_evidence=False):
        return self.text

    def reset(self):
        pass


# --- Results -------------------------------------------------------------------------------------------

def result(**overrides) -> RunResult:
    base = dict(scenario="port", attempt=1, diagnosis=True, analyst=None, fix=True, no_changes=None,
                tool_calls=4, tool_errors=0, denied=0, proposals=1, seconds=10.0, answer="ok")
    return RunResult(**{**base, **overrides})


def test_event_log_counts_matching_events():
    events = EventLog()
    events.log("tool", tool="a", ok=True)
    events.log("tool", tool="b", ok=False)
    events.log("approval", approved=False)
    assert (events.count("tool"), events.count("tool", ok=False), events.count("approval", approved=False)) == (2, 1, 1)


def test_tallies():
    assert tally([True, False, None, True]) == Tally(2, 3)
    assert str(Tally(2, 3)) == "2/3" and Tally(2, 3).rate == 66.7
    assert str(Tally()) == "-" and Tally().rate is None


def test_summary_and_json_report():
    results = [result(), result(attempt=2, fix=False, seconds=20.0, tool_calls=6),
               result(scenario="fine", diagnosis=None, fix=None, no_changes=True, proposals=0)]
    total = summarize("total", results)
    assert (str(total.passed), str(total.fix), total.seconds, total.tool_calls) == ("2/3", "1/2", 13.3, 4.7)
    assert [s.name for s in by_scenario(results)] == ["port", "fine"]

    report = json.loads(as_json(results, {"resolver": "qwen3:4b", "analyst": None}, "en", 2))
    assert report["total"]["passed"] == {"ok": 2, "total": 3, "rate": 66.7}
    assert report["models"]["resolver"] == "qwen3:4b" and len(report["runs"]) == 3
    assert report["runs"][1]["passed"] is False


def test_a_run_with_an_error_never_passes():
    assert result(error="timeout").passed is False
    assert result(answer="x" * 9000).as_dict()["answer"] == "x" * 4000
