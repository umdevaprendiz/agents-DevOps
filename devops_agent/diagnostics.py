"""Health report of containers and project, so a debugging session knows where to start.

Everything here is deterministic (no model): containers with problems and their recent
error lines, error lines in project log files, and the infrastructure files that usually
matter (Dockerfiles, compose, CI, Kubernetes, Terraform...). The agent redacts the output.
"""
from __future__ import annotations

from . import docker_tools as dk
from .i18n import t
from .monitor import ERROR_RE, Issue, Monitor
from .workspace import Workspace, WorkspaceError

ERRORS_PER_SOURCE = 5
CONTAINER_LOG_LINES = 300
LOG_SCAN_WINDOW = 3600  # seconds of container logs checked for repeated errors
LINE_CHARS = 200
MAX_INFRA_FILES = 40
INFRA_PATTERNS = (
    "Dockerfile*", "*.dockerfile", "docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml",
    ".dockerignore", ".github/workflows/*", ".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml",
    "k8s/*", "kubernetes/*", "helm/*", "charts/*", "*.tf", "nginx*.conf", "Makefile", "Procfile", ".env.example",
)


def collect(workspace: Workspace | None = None) -> str:
    sections = [_containers_section()]
    if workspace is not None:
        sections += [_project_logs_section(workspace), _infra_section(workspace)]
    return "\n\n".join(sections)


# --- Containers -----------------------------------------------------------------------------------

def _containers_section() -> str:
    try:
        issues = Monitor(scan_logs=True, log_window=LOG_SCAN_WINDOW).scan()
    except dk.DockerError as error:
        return t("diag.docker_unavailable", error=error)
    if not issues:
        return t("diag.containers_ok")
    return "\n".join([t("diag.containers_title"), *(_issue_block(issue) for issue in issues)])


def _issue_block(issue: Issue) -> str:
    return "\n".join([f"- {issue.container}: {issue.detail}", *_indented(_container_errors(issue.container))])


def _container_errors(container: str) -> list[str]:
    try:
        logs = dk.container_logs(container, tail=CONTAINER_LOG_LINES)
    except dk.DockerError:
        return []
    return _last_errors(logs.splitlines())


# --- Project logs ------------------------------------------------------------------------------------

def _project_logs_section(workspace: Workspace) -> str:
    blocks = [block for path in workspace.log_files() if (block := _log_block(workspace, path))]
    return "\n".join([t("diag.logs_title"), *blocks]) if blocks else t("diag.logs_ok")


def _log_block(workspace: Workspace, path: str) -> str | None:
    try:
        lines = workspace.tail_lines(path)
    except (WorkspaceError, OSError):
        return None
    errors = [line for line in lines if ERROR_RE.search(line)]
    if not errors:
        return None
    return "\n".join([t("diag.log_file", path=path, count=len(errors)), *_indented(_last_errors(errors))])


# --- Infrastructure files ----------------------------------------------------------------------------

def _infra_section(workspace: Workspace) -> str:
    files = sorted({path for pattern in INFRA_PATTERNS for path in workspace.paths(pattern)})[:MAX_INFRA_FILES]
    return "\n".join([t("diag.infra_title"), *(f"- {path}" for path in files)]) if files else t("diag.infra_none")


# --- Helpers ------------------------------------------------------------------------------------------

def _last_errors(lines: list[str]) -> list[str]:
    return [line.strip()[:LINE_CHARS] for line in lines if ERROR_RE.search(line)][-ERRORS_PER_SOURCE:]


def _indented(lines: list[str]) -> list[str]:
    return [f"    {line}" for line in lines]
