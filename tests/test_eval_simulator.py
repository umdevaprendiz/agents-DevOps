"""The simulated Docker answers the real docker_tools code: no Docker daemon needed."""
import threading

import pytest

from devops_agent import docker_tools as dk
from devops_agent.evaluation.simulator import ContainerSpec, SimulatedDocker, SimulationError
from devops_agent.monitor import Monitor


def spec(**overrides) -> ContainerSpec:
    return ContainerSpec.from_dict({"name": "web", **overrides})


@pytest.fixture
def docker(monkeypatch):
    """Installs a simulated daemon; the real docker CLI must never run."""
    def no_cli(*args):
        raise AssertionError("the real docker CLI was called")

    monkeypatch.setattr(dk, "_docker_cli", no_cli)

    def install(*specs: ContainerSpec) -> SimulatedDocker:
        simulated = SimulatedDocker(list(specs))
        context = dk.use_backend(simulated)
        context.__enter__()
        installed.append(context)
        return simulated

    installed = []
    yield install
    for context in installed:
        context.__exit__(None, None, None)


# --- docker ps / inspect / logs / stats ------------------------------------------------------------------

def test_ps_lists_running_containers_unless_all_are_requested(docker):
    docker(spec(name="web"), spec(name="worker", state="exited", exit_code=2), spec(name="api", state="restarting"))
    assert [c["name"] for c in dk.list_containers(include_stopped=False)] == ["web", "api"]
    assert [c["name"] for c in dk.list_containers()] == ["web", "worker", "api"]


def test_ps_status_text_looks_like_docker(docker):
    docker(spec(name="web", health="unhealthy"), spec(name="job", state="exited", exit_code=137, finished_minutes_ago=4))
    status = {c["name"]: c["status"] for c in dk.list_containers()}
    assert status == {"web": "Up 30 minutes (unhealthy)", "job": "Exited (137) 4 minutes ago"}


def test_inspect_goes_through_the_real_summary(docker):
    docker(spec(
        name="report", state="exited", exit_code=137, oom_killed=True, memory_mb=64, user="10001",
        command=["python", "report.py"], env=["BATCH_SIZE", "PATH"], ports={"80/tcp": ["127.0.0.1:8080"]},
        mounts=["/srv/data:/data"], healthcheck=["CMD", "true"], restart_policy="on-failure",
    ))
    info = dk.inspect_container("report")
    assert (info["status"], info["exit_code"], info["oom_killed"], info["memory_limit_mb"]) == ("exited", 137, True, 64)
    assert info["command"] == ["python", "report.py"] and info["env_vars"] == ["BATCH_SIZE", "PATH"]
    assert info["ports"] == {"80/tcp": ["127.0.0.1:8080"]} and info["mounts"] == ["/srv/data:/data"]
    assert (info["user"], info["restart_policy"], info["healthcheck"]) == ("10001", "on-failure", ["CMD", "true"])
    assert dk.parse_docker_time(info["finished_at"]) is not None


def test_health_log_and_failing_streak(docker):
    docker(spec(health="unhealthy", health_log=["connection refused"] * 2))
    info = dk.inspect_container("web")
    assert info["health"] == "unhealthy" and info["health_failing_streak"] == 3
    assert info["last_health_checks"] == [{"exit_code": 1, "output": "connection refused"}] * 2


def test_unknown_container_fails_like_docker(docker):
    docker(spec())
    with pytest.raises(dk.DockerError, match="No such container: api"):
        dk.inspect_container("api")
    with pytest.raises(dk.DockerError, match="No such container"):
        dk.container_logs("api")  # logs merge stderr into stdout


def test_logs_respect_tail(docker):
    docker(spec(logs="one\ntwo\nthree\n"))
    assert dk.container_logs("web", tail=2) == "two\nthree"


def test_stats_show_the_memory_limit_of_running_containers(docker):
    docker(spec(memory_mb=128), spec(name="old", state="exited"))
    (row,) = dk.container_stats()
    assert row["name"] == "web" and row["memory"] == "24MiB / 128MiB"


def test_actions_are_recorded_and_unsupported_commands_fail(docker):
    simulated = docker(spec())
    assert "web" in dk.restart_container("web")
    assert simulated.actions == [("restart", "web")]
    with pytest.raises(dk.DockerError, match="not supported"):
        dk._run(["system", "prune", "-f"])


def test_every_command_is_recorded(docker):
    simulated = docker(spec())
    dk.server_version()
    dk.list_containers()
    assert simulated.commands[0][0] == "version" and simulated.commands[1][:2] == ["ps", "-a"]


# --- The rest of the agent sees the simulation ----------------------------------------------------------------

def test_the_monitor_finds_the_simulated_problems(docker):
    docker(
        spec(name="web", health="unhealthy"),
        spec(name="api", state="restarting", exit_code=1, restart_count=9),
        spec(name="job", state="exited", exit_code=137, oom_killed=True),
        spec(name="ok"),
    )
    assert sorted(issue.container for issue in Monitor().scan()) == ["api", "job", "web"]


def test_backend_is_restored_and_local_to_the_thread(docker):
    seen = []
    with dk.use_backend(SimulatedDocker([spec()])):
        assert dk._BACKEND.get() is not None
        worker = threading.Thread(target=lambda: seen.append(dk._BACKEND.get()))
        worker.start()
        worker.join()
    assert seen == [None]
    assert dk._BACKEND.get() is None


# --- Container descriptions -------------------------------------------------------------------------------

def test_numbers_in_lists_become_strings():
    container = ContainerSpec.from_dict({"name": "w", "user": "10001", "command": ["sleep", 5], "ports": {"80/tcp": [8080]}})
    assert container.command == ["sleep", "5"] and container.ports == {"80/tcp": ["8080"]}


@pytest.mark.parametrize(
    "data, message",
    [
        ({"name": "web", "colour": "red"}, "colour"),
        ({"name": "web", "state": "sleeping"}, "state"),
        ({"name": "web", "health": "sick"}, "health"),
        ({"name": ""}, "name"),
        ("web", "mapping"),
    ],
)
def test_invalid_descriptions_are_rejected(data, message):
    with pytest.raises(SimulationError, match=message):
        ContainerSpec.from_dict(data)
