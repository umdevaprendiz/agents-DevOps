import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from devops_agent import docker_tools as dk
from devops_agent import i18n

# Built at runtime so secret scanners never see a password-looking literal in the source.
FAKE_SECRET = "not-a-real-" + "value-42"

RAW_INSPECT = {
    "Name": "/api",
    "RestartCount": 4,
    "State": {
        "Status": "exited",
        "ExitCode": 137,
        "OOMKilled": True,
        "Error": "",
        "StartedAt": "2026-10-23T19:00:00.000000001Z",
        "FinishedAt": "2026-10-23T19:05:00.5Z",
        "Health": {
            "Status": "unhealthy",
            "FailingStreak": 5,
            "Log": [{"ExitCode": 1, "Output": "curl: (7) Failed to connect\n"}] * 5,
        },
    },
    "Config": {
        "Image": "api:1.0",
        "Env": ["DB_PASSWORD=" + FAKE_SECRET, "PATH=/usr/bin"],
        "Cmd": ["node", "server.js"],
        "Entrypoint": None,
        "Healthcheck": {"Test": ["CMD", "curl", "-f", "http://localhost:3000"]},
    },
    "HostConfig": {"Memory": 268435456, "RestartPolicy": {"Name": "on-failure"}},
    "NetworkSettings": {
        "Ports": {"3000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3000"}], "9229/tcp": None},
        "Networks": {"bridge": {}, "backend": {}},
    },
}


class DockerCalls:
    """Records the docker commands that were built and returns an output chosen by the test."""

    def __init__(self):
        self.calls: list[dict] = []
        self.output = ""

    @property
    def last(self) -> dict:
        return self.calls[-1]

    def returns(self, output: str) -> None:
        self.output = output


@pytest.fixture
def docker_calls(monkeypatch):
    """Swaps dk._run for the recorder: no real docker command runs."""
    recorder = DockerCalls()

    def fake_run(args, timeout=dk.DEFAULT_TIMEOUT, merge_stderr=False):
        recorder.calls.append({"args": args, "timeout": timeout, "merge_stderr": merge_stderr})
        return recorder.output

    monkeypatch.setattr(dk, "_run", fake_run)
    return recorder


# --- Validation -----------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["api", "demo-web_1", "a.b", "3f9c2e1a7b4d"])
def test_name_accepts_valid_container_names(name):
    assert dk._name(name) == name


@pytest.mark.parametrize("name", ["", "x; rm -rf /", "a b", "../etc", "-rm", "$(whoami)", None, 42, "a" * 200])
def test_name_rejects_injection_and_invalid_values(name):
    with pytest.raises(dk.DockerError):
        dk._name(name)


@pytest.mark.parametrize("value", ["30s", "5m", "1h"])
def test_since_accepts_simple_durations(value):
    assert dk._since(value) == value


@pytest.mark.parametrize("value", ["30", "1d", "5m; ls", "2026-01-01"])
def test_since_rejects_other_formats(value):
    with pytest.raises(dk.DockerError):
        dk._since(value)


@pytest.mark.parametrize(
    "value, expected",
    [(True, True), (False, False), ("true", True), ("false", False), ("não", False), ("0", False), ("", False), (1, True)],
)
def test_as_bool_understands_model_values(value, expected):
    assert dk._as_bool(value) is expected


def test_clamp_limits_and_converts():
    assert dk._clamp("9999", 1, 500) == 500
    assert dk._clamp(-3, 1, 500) == 1
    assert dk._clamp(80, 1, 500) == 80


# --- Dates ------------------------------------------------------------------------------------------

def test_parse_docker_time_handles_nanoseconds_and_z():
    assert dk.parse_docker_time("2026-10-23T19:26:49.966566262Z") == datetime(
        2026, 10, 23, 19, 26, 49, 966566, tzinfo=timezone.utc
    )


def test_parse_docker_time_handles_offset_and_missing_fraction():
    parsed = dk.parse_docker_time("2026-10-23T16:00:00-03:00")
    assert parsed.utcoffset() == timedelta(hours=-3)


@pytest.mark.parametrize("value", [None, "", "0001-01-01T00:00:00Z", "yesterday"])
def test_parse_docker_time_returns_none_for_empty_or_invalid(value):
    assert dk.parse_docker_time(value) is None


# --- docker inspect summary ----------------------------------------------------------------------------

def test_summarize_extracts_diagnostic_fields():
    summary = dk._summarize(RAW_INSPECT)
    assert summary["name"] == "api"
    assert summary["status"] == "exited"
    assert summary["exit_code"] == 137
    assert summary["oom_killed"] is True
    assert summary["error"] is None
    assert summary["restart_count"] == 4
    assert summary["restart_policy"] == "on-failure"
    assert summary["memory_limit_mb"] == 256
    assert summary["image"] == "api:1.0"
    assert summary["networks"] == ["backend", "bridge"]


def test_summarize_keeps_only_last_three_health_checks():
    summary = dk._summarize(RAW_INSPECT)
    assert summary["health"] == "unhealthy"
    assert summary["health_failing_streak"] == 5
    assert summary["last_health_checks"] == [{"exit_code": 1, "output": "curl: (7) Failed to connect"}] * 3


def test_summarize_formats_port_bindings():
    assert dk._summarize(RAW_INSPECT)["ports"] == {"3000/tcp": ["0.0.0.0:3000"], "9229/tcp": None}


def test_summarize_never_exposes_env_values():
    summary = dk._summarize(RAW_INSPECT)
    assert summary["env_vars"] == ["DB_PASSWORD", "PATH"]
    assert FAKE_SECRET not in json.dumps(summary)


def test_summarize_includes_security_fields():
    raw = {
        **RAW_INSPECT,
        "Config": {**RAW_INSPECT["Config"], "User": "1000"},
        "HostConfig": {**RAW_INSPECT["HostConfig"], "Privileged": True, "NetworkMode": "host", "CapAdd": ["NET_ADMIN"]},
        "Mounts": [{"Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock"}],
    }
    summary = dk._summarize(raw)
    assert (summary["user"], summary["privileged"], summary["network_mode"]) == ("1000", True, "host")
    assert summary["cap_add"] == ["NET_ADMIN"]
    assert summary["mounts"] == ["/var/run/docker.sock:/var/run/docker.sock"]


def test_summarize_tolerates_missing_sections():
    summary = dk._summarize({"Name": "/x"})
    assert summary["name"] == "x"
    assert summary["restart_policy"] == "no"
    assert summary["env_vars"] == []


# --- Execution ----------------------------------------------------------------------------------------

def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr(dk.subprocess, "run", lambda *a, **k: _completed(stdout="ok\n"))
    assert dk._run(["ps"]) == "ok\n"


def test_run_never_uses_shell(monkeypatch):
    seen = {}

    def fake(cmd, **kwargs):
        seen.update(cmd=cmd, **kwargs)
        return _completed()

    monkeypatch.setattr(dk.subprocess, "run", fake)
    dk._run(["logs", "api"])
    assert seen["cmd"] == ["docker", "logs", "api"]
    assert not seen.get("shell")


def test_run_raises_with_stderr_message(monkeypatch):
    monkeypatch.setattr(dk.subprocess, "run", lambda *a, **k: _completed(1, stderr="No such container: x\n"))
    with pytest.raises(dk.DockerError, match="No such container: x"):
        dk._run(["inspect", "x"])


def test_run_reads_error_from_stdout_when_streams_are_merged(monkeypatch):
    monkeypatch.setattr(dk.subprocess, "run", lambda *a, **k: _completed(1, stdout="boom", stderr=None))
    with pytest.raises(dk.DockerError, match="boom"):
        dk._run(["logs", "x"], merge_stderr=True)


def test_run_reports_exit_code_when_there_is_no_message(monkeypatch):
    monkeypatch.setattr(dk.subprocess, "run", lambda *a, **k: _completed(3))
    with pytest.raises(dk.DockerError, match="code 3"):
        dk._run(["ps"])


@pytest.mark.parametrize(
    "error, message",
    [(FileNotFoundError(), "not found"), (subprocess.TimeoutExpired("docker", 30), "longer than 30s")],
)
def test_run_wraps_os_errors(monkeypatch, error, message):
    def fake(*args, **kwargs):
        raise error

    monkeypatch.setattr(dk.subprocess, "run", fake)
    with pytest.raises(dk.DockerError, match=message):
        dk._run(["ps"])


# --- Commands that get built -------------------------------------------------------------------------

def test_list_containers_parses_json_lines(docker_calls):
    docker_calls.returns(
        '{"Names":"web","Image":"nginx","State":"running","Status":"Up 1 hour"}\n'
        '{"Names":"api","Image":"node","State":"exited","Status":"Exited (1)"}\n'
    )
    assert dk.list_containers() == [
        {"name": "web", "image": "nginx", "state": "running", "status": "Up 1 hour"},
        {"name": "api", "image": "node", "state": "exited", "status": "Exited (1)"},
    ]
    assert docker_calls.last["args"][:2] == ["ps", "-a"]


def test_list_containers_can_skip_stopped(docker_calls):
    dk.list_containers(include_stopped="false")
    assert "-a" not in docker_calls.last["args"]


def test_container_logs_clamps_tail_and_merges_stderr(docker_calls):
    docker_calls.returns("line\n")
    assert dk.container_logs("api", tail=9999, since="30s") == "line"
    assert docker_calls.last["args"] == ["logs", "--tail", "500", "--since", "30s", "api"]
    assert docker_calls.last["merge_stderr"] is True


def test_container_logs_reports_empty_output_in_current_language(docker_calls):
    assert dk.container_logs("api") == "(no logs)"
    i18n.set_language("pt-BR")
    assert dk.container_logs("api") == "(sem logs)"


def test_inspect_containers_with_no_names_skips_docker(docker_calls):
    assert dk.inspect_containers([]) == []
    assert docker_calls.calls == []


def test_inspect_container_summarizes_result(docker_calls):
    docker_calls.returns(json.dumps([RAW_INSPECT]))
    assert dk.inspect_container("api")["exit_code"] == 137
    assert docker_calls.last["args"] == ["inspect", "--type", "container", "api"]


@pytest.mark.parametrize(
    "func, command, done",
    [
        (dk.restart_container, "restart", "restarted"),
        (dk.start_container, "start", "started"),
        (dk.stop_container, "stop", "stopped"),
    ],
)
def test_actions_run_expected_command(docker_calls, func, command, done):
    assert func("api") == f"Container 'api' {done}."
    assert docker_calls.last["args"] == [command, "api"]
    assert docker_calls.last["timeout"] == dk.ACTION_TIMEOUT


def test_actions_validate_name_before_running(docker_calls):
    with pytest.raises(dk.DockerError):
        dk.restart_container("api; docker rm -f db")
    assert docker_calls.calls == []
