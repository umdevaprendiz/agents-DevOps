import pytest

from devops_agent import diagnostics
from devops_agent import docker_tools as dk
from devops_agent.monitor import Issue
from devops_agent.workspace import Workspace
from tests.conftest import git, write


@pytest.fixture
def broken_containers(monkeypatch):
    issues = [Issue("api", ("stopped with exit code 1",))]
    monkeypatch.setattr(diagnostics.Monitor, "scan", lambda self: issues)
    monkeypatch.setattr(
        dk, "container_logs", lambda container, tail: "starting\nERROR: could not connect to database\nbye"
    )


@pytest.fixture
def healthy_containers(monkeypatch):
    monkeypatch.setattr(diagnostics.Monitor, "scan", lambda self: [])


@pytest.fixture
def no_docker(monkeypatch):
    def down(self):
        raise dk.DockerError("daemon not running")

    monkeypatch.setattr(diagnostics.Monitor, "scan", down)


@pytest.fixture
def project(tmp_path) -> Workspace:
    root = tmp_path / "project"
    write(root, "Dockerfile", "FROM python:3.12-slim\n")
    write(root, "docker-compose.yml", "services: {}\n")
    write(root, ".github/workflows/ci.yml", "on: push\n")
    write(root, "k8s/deploy.yaml", "apiVersion: apps/v1\n")
    write(root, "src/app.py", "print('ok')\n")
    write(root, "logs/app.log", "INFO started\nTypeError: Cannot read properties of undefined\nINFO done\n")
    write(root, "logs/quiet.log", "INFO all good\n")
    write(root, "logs/audit.jsonl", '{"event": "ERROR in a json line"}\n')
    write(root, ".venv/lib/pip.log", "ERROR: vendored noise\n")
    return Workspace(root)


# --- Containers -------------------------------------------------------------------------------------

def test_containers_with_problems_show_their_recent_errors(broken_containers):
    report = diagnostics.collect()
    assert "Containers with problems:" in report
    assert "- api: stopped with exit code 1" in report
    assert "    ERROR: could not connect to database" in report
    assert "starting" not in report


def test_healthy_containers(healthy_containers):
    assert diagnostics.collect() == "Containers: no problems detected."


def test_docker_down_still_reports_the_project(no_docker, project):
    report = diagnostics.collect(project)
    assert "Docker unavailable (daemon not running)" in report
    assert "Infrastructure files:" in report


# --- Project ------------------------------------------------------------------------------------------

def test_project_log_files_with_errors_are_reported(healthy_containers, project):
    report = diagnostics.collect(project)
    assert "- logs/app.log (1 error lines, latest:)" in report
    assert "    TypeError: Cannot read properties of undefined" in report
    assert "quiet.log" not in report
    assert "audit.jsonl" not in report
    assert "vendored noise" not in report


def test_git_ignored_log_files_are_still_scanned(healthy_containers, git_repo):
    write(git_repo, ".gitignore", "logs/\n")
    git(git_repo, "add", ".gitignore")
    git(git_repo, "commit", "-q", "-m", "ignore logs")
    write(git_repo, "logs/worker.log", "panic: missing required environment variable QUEUE_URL\n")
    assert "panic: missing required environment variable QUEUE_URL" in diagnostics.collect(Workspace(git_repo))


def test_infrastructure_files_are_listed(healthy_containers, project):
    report = diagnostics.collect(project)
    for path in ("Dockerfile", "docker-compose.yml", ".github/workflows/ci.yml", "k8s/deploy.yaml"):
        assert f"- {path}" in report
    assert "src/app.py" not in report


def test_project_without_logs_or_infrastructure(healthy_containers, tmp_path):
    write(tmp_path, "notes.txt", "hello\n")
    report = diagnostics.collect(Workspace(tmp_path))
    assert "Project log files: no errors found." in report
    assert "Infrastructure files: none found." in report


def test_tail_lines_reads_only_the_end_of_big_files(project):
    write(project.root, "logs/big.log", "first line\n" + "x" * 50 + "\nlast line\n")
    assert project.tail_lines("logs/big.log", max_bytes=20) == ["last line"]
