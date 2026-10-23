import os
import re
from pathlib import Path

import pytest

from devops_agent import config as config_module
from devops_agent.config import Config, load_env_file, parse_env

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def clean_env(monkeypatch):
    """Isolated environment: no AGENT_*, OLLAMA_* or DOCKER_* variables from the developer machine."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENT_", "OLLAMA_", "DOCKER_"))}
    monkeypatch.setattr(os, "environ", env)
    return env


# --- .env parsing --------------------------------------------------------------------------------

def test_parse_env_reads_names_and_values():
    text = (
        "# comment\n\n"
        "AGENT_MODEL=qwen3:8b\n"
        "export AGENT_WORKERS=4\n"
        'OLLAMA_HOST="http://gpu-server:11434"\n'
        "AGENT_LANGUAGE=\n"
        "NOT_AN_ASSIGNMENT\n"
        "WITH_EQUALS=a=b\n"
    )
    assert parse_env(text) == [
        ("AGENT_MODEL", "qwen3:8b"),
        ("AGENT_WORKERS", "4"),
        ("OLLAMA_HOST", "http://gpu-server:11434"),
        ("WITH_EQUALS", "a=b"),
    ]


def test_load_env_file_never_overrides_real_environment(tmp_path, clean_env):
    env_file = tmp_path / ".env"
    env_file.write_text("AGENT_MODEL=from-file\nAGENT_WORKERS=5\n", encoding="utf-8")
    clean_env["AGENT_MODEL"] = "from-environment"

    assert load_env_file(env_file) is True
    assert clean_env["AGENT_MODEL"] == "from-environment"
    assert clean_env["AGENT_WORKERS"] == "5"


def test_load_env_file_skips_missing_file(tmp_path, clean_env):
    assert load_env_file(tmp_path / "missing.env") is False


def test_load_env_file_location_can_be_configured(tmp_path, clean_env):
    env_file = tmp_path / "custom.env"
    env_file.write_text("AGENT_WORKERS=7\n", encoding="utf-8")
    clean_env["AGENT_ENV_FILE"] = str(env_file)

    assert load_env_file() is True
    assert clean_env["AGENT_WORKERS"] == "7"


# --- Config ---------------------------------------------------------------------------------------

def test_empty_variables_fall_back_to_defaults(clean_env):
    clean_env.update(AGENT_MODEL="", AGENT_WORKERS="", AGENT_MAX_STEPS="  ")
    cfg = Config()
    assert (cfg.model, cfg.workers, cfg.max_steps) == ("qwen3:4b", 2, 12)


def test_variables_override_defaults(clean_env):
    clean_env.update(AGENT_MODEL="qwen3:8b", AGENT_WORKERS="8", AGENT_AUDIT_FILE="/data/audit.jsonl")
    cfg = Config()
    assert (cfg.model, cfg.workers, cfg.audit_file) == ("qwen3:8b", 8, Path("/data/audit.jsonl"))


def test_fast_model_is_optional(clean_env):
    cfg = Config()
    assert cfg.fast_model is None
    assert cfg.models() == ["qwen3:4b"]


def test_fast_model_and_unique_model_list(clean_env):
    clean_env.update(AGENT_MODEL="qwen3:8b", AGENT_FAST_MODEL="qwen3:4b")
    assert Config().models() == ["qwen3:8b", "qwen3:4b"]
    clean_env["AGENT_FAST_MODEL"] = "qwen3:8b"
    assert Config().models() == ["qwen3:8b"]


def test_language_variable_is_normalized(clean_env):
    clean_env["AGENT_LANGUAGE"] = "pt_BR"
    assert Config().language == "pt-BR"


# --- .env.example ---------------------------------------------------------------------------------

def _example_lines() -> list[str]:
    return (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()


def test_env_example_holds_only_variable_names():
    """Public repository rule: no values, not even examples."""
    for line in _example_lines():
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*=", line), f"unexpected line in .env.example: {line!r}"


def test_env_example_lists_every_agent_variable():
    source = Path(config_module.__file__).read_text(encoding="utf-8")
    used = set(re.findall(r'"(AGENT_[A-Z_]+)"', source)) - {"AGENT_ENV_FILE"}
    listed = {line.rstrip("=") for line in _example_lines()}
    assert used <= listed
