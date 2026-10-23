"""Agent settings, read from environment variables or from a .env file (never committed)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import i18n

ENV_FILE_VARIABLE = "AGENT_ENV_FILE"
DEFAULT_ENV_FILE = ".env"


def _env(name: str, default: str | None = None) -> str | None:
    """Reads a variable; an empty value counts as unset."""
    value = os.environ.get(name, "").strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


@dataclass
class Config:
    model: str = field(default_factory=lambda: _env("AGENT_MODEL", "qwen3:4b"))
    # None lets the Ollama library use OLLAMA_HOST or http://localhost:11434
    ollama_host: str | None = field(default_factory=lambda: _env("OLLAMA_HOST"))
    language: str = field(default_factory=lambda: i18n.detect_language(_env("AGENT_LANGUAGE")))
    workers: int = field(default_factory=lambda: _env_int("AGENT_WORKERS", 2))
    max_steps: int = field(default_factory=lambda: _env_int("AGENT_MAX_STEPS", 12))
    num_ctx: int = field(default_factory=lambda: _env_int("AGENT_NUM_CTX", 8192))
    max_tool_output: int = field(default_factory=lambda: _env_int("AGENT_MAX_TOOL_OUTPUT", 4000))
    audit_file: Path = field(default_factory=lambda: Path(_env("AGENT_AUDIT_FILE", "logs/audit.jsonl")))
    # Project the agent reads and proposes changes to (a git repository).
    workspace: Path = field(default_factory=lambda: Path(_env("AGENT_WORKSPACE", ".")))


# --- .env file ------------------------------------------------------------------------------------

def load_env_file(path: str | Path | None = None) -> bool:
    """Loads KEY=VALUE lines into os.environ. Variables already set win and empty values are skipped."""
    env_path = Path(path or _env(ENV_FILE_VARIABLE, DEFAULT_ENV_FILE))
    if not env_path.is_file():
        return False
    for key, value in parse_env(env_path.read_text(encoding="utf-8")):
        os.environ.setdefault(key, value)
    return True


def parse_env(text: str) -> list[tuple[str, str]]:
    return [pair for line in text.splitlines() if (pair := _parse_env_line(line))]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.removeprefix("export ").strip()
    value = _unquote(value.strip())
    return (key, value) if key and value else None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
