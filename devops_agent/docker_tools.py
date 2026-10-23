"""Docker access through the CLI.

Commands always run as an argument list (never through a shell) and container names
are validated, so the model cannot inject arbitrary commands. DOCKER_HOST and
DOCKER_CONTEXT are honored, which lets the agent watch a remote daemon.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime

from .i18n import t

MAX_LOG_LINES = 500
DEFAULT_TIMEOUT = 30
ACTION_TIMEOUT = 120
STATS_TIMEOUT = 45

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_SINCE_RE = re.compile(r"^\d+[smh]$")
_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})")
_FALSE_WORDS = {"false", "0", "no", "nao", "não", ""}


class DockerError(Exception):
    """Any failure running a docker command."""


# --- Execution ------------------------------------------------------------------------------------

def _run(args: list[str], timeout: int = DEFAULT_TIMEOUT, merge_stderr: bool = False) -> str:
    proc = _invoke(args, timeout, merge_stderr)
    if proc.returncode != 0:
        raise DockerError(_error_message(proc, args))
    return proc.stdout


def _invoke(args: list[str], timeout: int, merge_stderr: bool) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["docker", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise DockerError(t("docker.cli_missing")) from error
    except subprocess.TimeoutExpired as error:
        raise DockerError(t("docker.timeout", command=args[0], seconds=timeout)) from error


def _error_message(proc: subprocess.CompletedProcess, args: list[str]) -> str:
    # With merge_stderr the error arrives on stdout (stderr is None).
    output = proc.stderr if proc.stderr is not None else proc.stdout
    return (output or "").strip() or t("docker.exit_code", command=args[0], code=proc.returncode)


# --- Validation and conversion ----------------------------------------------------------------------

def _name(value) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise DockerError(t("docker.invalid_name", value=repr(value)))
    return value


def _since(value: str) -> str:
    if not _SINCE_RE.match(value):
        raise DockerError(t("docker.invalid_since", value=repr(value)))
    return value


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_WORDS
    return bool(value)


def _clamp(value, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def parse_docker_time(value: str | None) -> datetime | None:
    """Parses '2026-10-23T19:20:01.123456789Z' (Docker uses nanoseconds)."""
    if not value or value.startswith("0001-"):
        return None
    match = _TIME_RE.match(value)
    if not match:
        return None
    base, fraction, offset = match.groups()
    return datetime.fromisoformat(base + _microseconds(fraction) + _utc_offset(offset))


def _microseconds(fraction: str | None) -> str:
    return "." + fraction[:6].ljust(6, "0") if fraction else ""


def _utc_offset(offset: str) -> str:
    return "+00:00" if offset == "Z" else offset


# --- Read-only commands -------------------------------------------------------------------------------

def server_version() -> str:
    return _run(["version", "--format", "{{.Server.Version}}"]).strip()


def list_containers(include_stopped=True) -> list[dict]:
    args = ["ps", "-a"] if _as_bool(include_stopped) else ["ps"]
    return [_container_row(row) for row in _json_lines(_run([*args, "--format", "{{json .}}"]))]


def _container_row(row: dict) -> dict:
    return {"name": row.get("Names"), "image": row.get("Image"), "state": row.get("State"), "status": row.get("Status")}


def inspect_containers(names: list[str]) -> list[dict]:
    if not names:
        return []
    raw = json.loads(_run(["inspect", "--type", "container", *map(_name, names)]))
    return [_summarize(item) for item in raw]


def inspect_container(container: str) -> dict:
    return inspect_containers([container])[0]


def container_logs(container: str, tail=80, since: str | None = None) -> str:
    args = ["logs", "--tail", str(_clamp(tail, 1, MAX_LOG_LINES))]
    if since:
        args += ["--since", _since(since)]
    return _run([*args, _name(container)], merge_stderr=True).strip() or t("docker.no_logs")


def container_stats(container: str | None = None) -> list[dict]:
    args = ["stats", "--no-stream", "--format", "{{json .}}"]
    if container:
        args.append(_name(container))
    return [_stats_row(row) for row in _json_lines(_run(args, timeout=STATS_TIMEOUT))]


def _stats_row(row: dict) -> dict:
    return {
        "name": row.get("Name"),
        "cpu": row.get("CPUPerc"),
        "memory": row.get("MemUsage"),
        "memory_pct": row.get("MemPerc"),
        "net_io": row.get("NetIO"),
        "block_io": row.get("BlockIO"),
        "pids": row.get("PIDs"),
    }


# --- docker inspect summary ------------------------------------------------------------------------------

def _summarize(raw: dict) -> dict:
    """Reduces the huge docker inspect JSON to the fields that matter for a diagnosis."""
    return {
        "name": raw.get("Name", "").lstrip("/"),
        **_state_summary(raw),
        **_health_summary(raw),
        **_host_summary(raw),
        **_config_summary(raw),
        **_network_summary(raw),
    }


def _state_summary(raw: dict) -> dict:
    state = raw.get("State") or {}
    return {
        "status": state.get("Status"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "error": state.get("Error") or None,
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "restart_count": raw.get("RestartCount", 0),
    }


def _health_summary(raw: dict) -> dict:
    health = (raw.get("State") or {}).get("Health") or {}
    return {
        "health": health.get("Status"),
        "health_failing_streak": health.get("FailingStreak"),
        "last_health_checks": [_health_check(entry) for entry in (health.get("Log") or [])[-3:]],
    }


def _health_check(entry: dict) -> dict:
    return {"exit_code": entry.get("ExitCode"), "output": (entry.get("Output") or "").strip()[-300:]}


def _host_summary(raw: dict) -> dict:
    host = raw.get("HostConfig") or {}
    memory = host.get("Memory")
    return {
        "restart_policy": (host.get("RestartPolicy") or {}).get("Name") or "no",
        "memory_limit_mb": round(memory / 2**20) if memory else None,
        "privileged": bool(host.get("Privileged")),
        "network_mode": host.get("NetworkMode"),
        "cap_add": host.get("CapAdd") or [],
        "mounts": [f"{m.get('Source')}:{m.get('Destination')}" for m in raw.get("Mounts") or []],
    }


def _config_summary(raw: dict) -> dict:
    config = raw.get("Config") or {}
    return {
        "image": config.get("Image"),
        "user": config.get("User") or "",
        "healthcheck": (config.get("Healthcheck") or {}).get("Test"),
        "entrypoint": config.get("Entrypoint"),
        "command": config.get("Cmd"),
        # Only the variable names: values may hold secrets.
        "env_vars": [entry.split("=", 1)[0] for entry in config.get("Env") or []],
    }


def _network_summary(raw: dict) -> dict:
    network = raw.get("NetworkSettings") or {}
    return {
        "ports": {port: _bindings(binds) for port, binds in (network.get("Ports") or {}).items()},
        "networks": sorted((network.get("Networks") or {}).keys()),
    }


def _bindings(binds: list[dict] | None) -> list[str] | None:
    return [f"{b.get('HostIp')}:{b.get('HostPort')}" for b in binds] if binds else None


# --- Actions (the agent always asks for human approval first) ---------------------------------------------

def restart_container(container: str) -> str:
    return _container_action("restart", container, "docker.restarted")


def start_container(container: str) -> str:
    return _container_action("start", container, "docker.started")


def stop_container(container: str) -> str:
    return _container_action("stop", container, "docker.stopped")


def _container_action(command: str, container: str, done_key: str) -> str:
    _run([command, _name(container)], timeout=ACTION_TIMEOUT)
    return t(done_key, container=container)
