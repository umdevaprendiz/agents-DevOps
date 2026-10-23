from datetime import timedelta
from types import SimpleNamespace

import pytest

from devops_agent import docker_tools as dk
from devops_agent import i18n
from devops_agent import monitor as monitor_module
from devops_agent.monitor import ERROR_RE, Issue, Monitor, _health_problem, _restart_problem
from devops_agent.redaction import MASK
from tests.conftest import NOW, docker_time


# --- Issue ----------------------------------------------------------------------------------------

def test_issue_joins_problems_and_builds_task():
    issue = Issue("api", ("stopped with exit code 1", "healthcheck failing"))
    assert issue.detail == "stopped with exit code 1; healthcheck failing"
    assert "'api'" in issue.task()
    assert issue.detail in issue.task()


def test_issue_task_follows_the_language():
    i18n.set_language("pt-BR")
    assert Issue("api", ("x",)).task().startswith("O monitor detectou")


# --- State rules ------------------------------------------------------------------------------------

def test_restarting_container_is_a_problem(make_info):
    info = make_info(status="restarting", restart_count=7, exit_code=2)
    assert Monitor()._state_problem(info, NOW) == "restart loop (7 restarts, last exit code 2)"


def test_dead_container_is_a_problem(make_info):
    assert Monitor()._state_problem(make_info(status="dead"), NOW) == "is in the 'dead' state"


def test_recent_failure_is_a_problem(make_info):
    info = make_info(status="exited", exit_code=1, finished_at=docker_time(NOW - timedelta(minutes=2)))
    assert Monitor()._state_problem(info, NOW) == "stopped with exit code 1"


def test_oom_kill_is_reported_even_with_exit_zero(make_info):
    info = make_info(status="exited", exit_code=0, oom_killed=True, finished_at=docker_time(NOW))
    assert "OOMKilled" in Monitor()._state_problem(info, NOW)


def test_clean_exit_is_ignored(make_info):
    info = make_info(status="exited", exit_code=0, finished_at=docker_time(NOW))
    assert Monitor()._state_problem(info, NOW) is None


def test_old_failures_are_ignored(make_info):
    info = make_info(status="exited", exit_code=1, finished_at=docker_time(NOW - timedelta(days=3)))
    assert Monitor()._state_problem(info, NOW) is None


def test_old_failure_window_is_configurable(make_info):
    info = make_info(status="exited", exit_code=1, finished_at=docker_time(NOW - timedelta(days=3)))
    assert Monitor(ignore_exited_older_than=timedelta(days=7))._state_problem(info, NOW)


def test_running_container_has_no_state_problem(make_info):
    assert Monitor()._state_problem(make_info(), NOW) is None


# --- Healthcheck -------------------------------------------------------------------------------------

def test_unhealthy_running_container_is_a_problem(make_info):
    info = make_info(health="unhealthy", health_failing_streak=4)
    assert _health_problem(info) == "healthcheck failing (4 consecutive failures)"


def test_stopped_container_keeps_stale_health_and_is_ignored(make_info):
    assert _health_problem(make_info(status="exited", health="unhealthy")) is None


# --- Restarts ------------------------------------------------------------------------------------------

def test_restart_count_increase_between_scans_is_a_problem(make_info):
    assert _restart_problem(make_info(restart_count=5), 3, NOW) == "restarted 2x since the last check"


def test_stable_restart_count_is_fine(make_info):
    assert _restart_problem(make_info(restart_count=5), 5, NOW) is None


def test_first_scan_detects_probable_loop(make_info):
    info = make_info(restart_count=6, started_at=docker_time(NOW - timedelta(seconds=30)))
    assert "probable loop" in _restart_problem(info, None, NOW)


def test_first_scan_ignores_old_restarts(make_info):
    info = make_info(restart_count=6, started_at=docker_time(NOW - timedelta(days=2)))
    assert _restart_problem(info, None, NOW) is None


def test_restart_rule_only_applies_to_running_containers(make_info):
    assert _restart_problem(make_info(status="restarting", restart_count=9), 1, NOW) is None


# --- Errors in the logs ------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line",
    [
        "ERROR: could not connect to database",
        "2026-10-23 FATAL out of memory",
        "panic: missing required environment variable",
        "Traceback (most recent call last):",
        "Exception in thread main",
        "time=... level=error msg=boom",
        '{"level": "error", "msg": "boom"}',
    ],
)
def test_error_regex_matches_common_error_lines(line):
    assert ERROR_RE.search(line)


@pytest.mark.parametrize("line", ["GET /health 200", "error_count=0", "no errors found", "INFO started"])
def test_error_regex_ignores_normal_lines(line):
    assert not ERROR_RE.search(line)


def _fake_logs(monkeypatch, text):
    monkeypatch.setattr(dk, "container_logs", lambda container, tail, since: text)


def test_log_scan_is_off_by_default(monkeypatch, make_info):
    _fake_logs(monkeypatch, "ERROR\nERROR\nERROR\n")
    assert Monitor()._log_problem(make_info()) is None


def test_log_scan_reports_when_threshold_is_reached(monkeypatch, make_info):
    _fake_logs(monkeypatch, "ok\nERROR a\nERROR b\nERROR c\n")
    problem = Monitor(scan_logs=True, log_window=60)._log_problem(make_info())
    assert problem.startswith("3 error lines in the logs in the last 60s")
    assert problem.endswith("ERROR c")


def test_log_example_is_redacted(monkeypatch, make_info):
    secret = "hunter" + "2-" + "x" * 12
    _fake_logs(monkeypatch, f"ERROR login failed password={secret}\n" * 3)
    problem = Monitor(scan_logs=True)._log_problem(make_info())
    assert secret not in problem
    assert MASK in problem


def test_log_scan_ignores_few_errors(monkeypatch, make_info):
    _fake_logs(monkeypatch, "ERROR a\nERROR b\n")
    assert Monitor(scan_logs=True)._log_problem(make_info()) is None


# --- Full scan ------------------------------------------------------------------------------------------

@pytest.fixture
def fake_docker(monkeypatch):
    """Simulates docker ps + docker inspect with the containers defined by the test."""
    state = SimpleNamespace(infos=[], inspected=[])

    def list_containers(include_stopped=True):
        return [{"name": info["name"]} for info in state.infos]

    def inspect_containers(names):
        state.inspected.append(names)
        return [info for info in state.infos if info["name"] in names]

    monkeypatch.setattr(dk, "list_containers", list_containers)
    monkeypatch.setattr(dk, "inspect_containers", inspect_containers)
    return state


def test_scan_returns_only_containers_with_problems(fake_docker, make_info):
    fake_docker.infos = [
        make_info(name="web"),
        make_info(name="api", status="exited", exit_code=1, finished_at=docker_time(NOW)),
    ]
    issues = Monitor().scan()
    assert [issue.container for issue in issues] == ["api"]


def test_scan_groups_all_problems_of_a_container(fake_docker, make_info):
    fake_docker.infos = [
        make_info(name="api", health="unhealthy", health_failing_streak=2, restart_count=4, started_at=docker_time(NOW))
    ]
    (issue,) = Monitor().scan()
    assert len(issue.problems) == 2


def test_scan_respects_only_filter(fake_docker, make_info):
    fake_docker.infos = [make_info(name="web"), make_info(name="api")]
    Monitor(only={"api"}).scan()
    assert fake_docker.inspected == [["api"]]


def test_scan_remembers_restart_counts_between_runs(fake_docker, make_info):
    monitor = Monitor()
    fake_docker.infos = [make_info(name="api", restart_count=1)]
    assert monitor.scan() == []
    fake_docker.infos = [make_info(name="api", restart_count=2)]
    (issue,) = monitor.scan()
    assert issue.problems == ("restarted 1x since the last check",)


# --- Cooldown ---------------------------------------------------------------------------------------------

def test_due_applies_cooldown_per_container(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(monitor_module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monitor = Monitor(cooldown=600)
    api, web = Issue("api", ("x",)), Issue("web", ("y",))

    assert monitor.due([api]) == [api]
    clock.now += 60
    assert monitor.due([api, web]) == [web]
    clock.now += 600
    assert monitor.due([api, web]) == [api, web]
