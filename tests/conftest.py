"""Shared fixtures. Unit tests need neither Docker nor Ollama running."""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from ollama import Message

from devops_agent import i18n

NOW = datetime.now(timezone.utc)

COMPOSE = (
    "services:\n"
    "  web:\n"
    "    image: nginx:alpine\n"
    "    healthcheck:\n"
    '      test: ["CMD", "wget", "-q", "http://localhost:8081/"]\n'
)
GIT_TEST_CONFIG = {
    "user.name": "Test Operator",
    "user.email": "operator@example.com",
    "core.autocrlf": "false",
    "commit.gpgsign": "false",
}


def write(root: Path, relative: str, text: str) -> Path:
    """Writes a file with exact bytes (no newline translation on Windows)."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def git_repo(tmp_path) -> Path:
    """A small git repository with one commit (skipped when git is not installed)."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for key, value in GIT_TEST_CONFIG.items():
        git(repo, "config", key, value)
    write(repo, "docker-compose.yml", COMPOSE)
    write(repo, "app/config.yml", "port: 3000\nlog_level: info\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture(autouse=True)
def english():
    """Tests assert English texts; a test can switch with i18n.set_language and is reset afterwards."""
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def docker_time(moment: datetime) -> str:
    """Formats a date the way Docker does: nanoseconds and a Z suffix."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def assistant(content: str = "", calls: list[tuple[str, dict]] | None = None) -> Message:
    """A model message. calls = [(tool_name, arguments), ...]."""
    tool_calls = [Message.ToolCall(function=Message.ToolCall.Function(name=n, arguments=a)) for n, a in calls or []]
    return Message(role="assistant", content=content, tool_calls=tool_calls or None)


class FakeClient:
    """Replaces ollama.Client: returns scripted replies and records every call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(message=reply)


@pytest.fixture
def make_info():
    """Builds the dict returned by docker_tools._summarize, defaulting to a healthy container."""

    def factory(**overrides) -> dict:
        info = {
            "name": "app",
            "status": "running",
            "exit_code": 0,
            "oom_killed": False,
            "error": None,
            "started_at": docker_time(NOW - timedelta(hours=1)),
            "finished_at": "0001-01-01T00:00:00Z",
            "restart_count": 0,
            "health": None,
            "health_failing_streak": None,
        }
        info.update(overrides)
        return info

    return factory
