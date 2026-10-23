"""Acesso ao Docker pela CLI.

Tudo roda com lista de argumentos (sem shell) e os nomes de container são
validados, então o modelo não consegue injetar comandos arbitrários.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_SINCE_RE = re.compile(r"^\d+[smh]$")


class DockerError(Exception):
    """Falha ao executar um comando docker."""


def _run(args: list[str], timeout: int = 30, merge_stderr: bool = False) -> str:
    try:
        proc = subprocess.run(
            ["docker", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as e:
        raise DockerError("Docker CLI não encontrado no PATH.") from e
    except subprocess.TimeoutExpired as e:
        raise DockerError(f"'docker {args[0]}' excedeu {timeout}s.") from e
    if proc.returncode != 0:
        msg = (proc.stdout if merge_stderr else proc.stderr) or ""
        raise DockerError(msg.strip() or f"'docker {args[0]}' saiu com código {proc.returncode}")
    return proc.stdout


def _name(value) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise DockerError(f"nome de container inválido: {value!r}")
    return value


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "nao", "não", "")
    return bool(value)


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def parse_docker_time(value: str | None) -> datetime | None:
    """Converte '2026-10-23T19:20:01.123456789Z' em datetime (Docker usa nanossegundos)."""
    if not value or value.startswith("0001-"):
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})", value)
    if not m:
        return None
    frac = "." + m.group(2)[:6].ljust(6, "0") if m.group(2) else ""
    tz = "+00:00" if m.group(3) == "Z" else m.group(3)
    return datetime.fromisoformat(m.group(1) + frac + tz)


def server_version() -> str:
    return _run(["version", "--format", "{{.Server.Version}}"]).strip()


def list_containers(include_stopped=True) -> list[dict]:
    args = ["ps", "--format", "{{json .}}"]
    if _as_bool(include_stopped):
        args.insert(1, "-a")
    return [
        {"name": r.get("Names"), "image": r.get("Image"), "state": r.get("State"), "status": r.get("Status")}
        for r in _json_lines(_run(args))
    ]


def _summarize(raw: dict) -> dict:
    state = raw.get("State") or {}
    health = state.get("Health") or {}
    cfg = raw.get("Config") or {}
    host = raw.get("HostConfig") or {}
    net = raw.get("NetworkSettings") or {}
    ports = {
        port: [f"{b.get('HostIp')}:{b.get('HostPort')}" for b in binds] if binds else None
        for port, binds in (net.get("Ports") or {}).items()
    }
    return {
        "name": raw.get("Name", "").lstrip("/"),
        "image": cfg.get("Image"),
        "status": state.get("Status"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "error": state.get("Error") or None,
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "restart_count": raw.get("RestartCount", 0),
        "restart_policy": (host.get("RestartPolicy") or {}).get("Name") or "no",
        "memory_limit_mb": round(host["Memory"] / 2**20) if host.get("Memory") else None,
        "health": health.get("Status"),
        "health_failing_streak": health.get("FailingStreak"),
        "last_health_checks": [
            {"exit_code": h.get("ExitCode"), "output": (h.get("Output") or "").strip()[-300:]}
            for h in (health.get("Log") or [])[-3:]
        ],
        "healthcheck": (cfg.get("Healthcheck") or {}).get("Test"),
        "entrypoint": cfg.get("Entrypoint"),
        "command": cfg.get("Cmd"),
        "ports": ports,
        "networks": sorted((net.get("Networks") or {}).keys()),
        # Só os nomes das variáveis: os valores podem conter segredos.
        "env_vars": [e.split("=", 1)[0] for e in cfg.get("Env") or []],
    }


def inspect_containers(names: list[str]) -> list[dict]:
    if not names:
        return []
    raw = json.loads(_run(["inspect", "--type", "container", *[_name(n) for n in names]]))
    return [_summarize(r) for r in raw]


def inspect_container(container: str) -> dict:
    return inspect_containers([container])[0]


def container_logs(container: str, tail=80, since: str | None = None) -> str:
    tail = max(1, min(int(tail), 500))
    args = ["logs", "--tail", str(tail)]
    if since:
        if not _SINCE_RE.match(since):
            raise DockerError(f"valor inválido para since: {since!r}")
        args += ["--since", since]
    args.append(_name(container))
    return _run(args, merge_stderr=True).strip() or "(sem logs)"


def container_stats(container: str | None = None) -> list[dict]:
    args = ["stats", "--no-stream", "--format", "{{json .}}"]
    if container:
        args.append(_name(container))
    return [
        {
            "name": r.get("Name"),
            "cpu": r.get("CPUPerc"),
            "memory": r.get("MemUsage"),
            "memory_pct": r.get("MemPerc"),
            "net_io": r.get("NetIO"),
            "block_io": r.get("BlockIO"),
            "pids": r.get("PIDs"),
        }
        for r in _json_lines(_run(args, timeout=45))
    ]


def restart_container(container: str) -> str:
    _run(["restart", _name(container)], timeout=120)
    return f"Container '{container}' reiniciado."


def start_container(container: str) -> str:
    _run(["start", _name(container)], timeout=120)
    return f"Container '{container}' iniciado."


def stop_container(container: str) -> str:
    _run(["stop", _name(container)], timeout=120)
    return f"Container '{container}' parado."
