"""A Docker daemon simulated from a scenario.

It answers the docker CLI commands the agent runs (ps, inspect, logs, stats, version and
restart/start/stop) with the containers described in the scenario. Installed with
docker_tools.use_backend, every tool, the monitor, the diagnostics and the security audit
see these containers instead of the real ones, so no code path is faked.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone

from ..i18n import t

STATES = ("running", "exited", "restarting", "created", "paused", "dead")
HEALTH_STATES = ("healthy", "unhealthy", "starting")
LISTED_BY_PS = {"running", "restarting", "paused"}  # what `docker ps` (without -a) shows
ACTIONS = {"restart", "start", "stop"}
FLAGS_WITH_VALUE = {"--format", "--type", "--tail", "--since", "-n"}
ZERO_TIME = "0001-01-01T00:00:00Z"
VERSION = "27.0.0-simulated"
DEFAULT_TAIL = 100


class SimulationError(Exception):
    """A container description that cannot be simulated."""


class _CommandFailed(Exception):
    """A docker command that fails, like `docker inspect missing` does."""


# --- Container description ------------------------------------------------------------------------

@dataclass
class ContainerSpec:
    """One container as the scenario describes it. Lists become docker's arrays."""

    name: str
    image: str = "app:latest"
    state: str = "running"
    exit_code: int = 0
    oom_killed: bool = False
    error: str = ""
    restart_count: int = 0
    restart_policy: str = "no"
    memory_mb: int | None = None
    user: str = ""
    privileged: bool = False
    network_mode: str = "bridge"
    cap_add: list[str] = field(default_factory=list)
    mounts: list[str] = field(default_factory=list)  # "source:destination"
    command: list[str] = field(default_factory=list)
    entrypoint: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)  # variable names (values are never needed)
    ports: dict[str, list[str]] = field(default_factory=dict)  # "80/tcp": ["0.0.0.0:8080"]
    networks: list[str] = field(default_factory=lambda: ["default"])
    healthcheck: list[str] = field(default_factory=list)
    health: str | None = None
    health_log: list[str] = field(default_factory=list)
    logs: str = ""
    started_minutes_ago: int = 30
    finished_minutes_ago: int = 2
    cpu: str = "0.50%"
    memory_used: str = "24MiB"

    @classmethod
    def from_dict(cls, data: dict) -> ContainerSpec:
        if not isinstance(data, dict):
            raise SimulationError(t("eval.error.container_mapping"))
        unknown = sorted(set(data) - {item.name for item in fields(cls)})
        if unknown:
            raise SimulationError(t("eval.error.container_fields", fields=", ".join(unknown)))
        spec = cls(**{key: _normalize(value) for key, value in data.items()})
        spec.validate()
        return spec

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise SimulationError(t("eval.error.container_name"))
        if self.state not in STATES:
            raise SimulationError(t("eval.error.container_value", name=self.name, field="state", values=", ".join(STATES)))
        if self.health is not None and self.health not in HEALTH_STATES:
            values = ", ".join(HEALTH_STATES)
            raise SimulationError(t("eval.error.container_value", name=self.name, field="health", values=values))

    @property
    def is_up(self) -> bool:
        return self.state in LISTED_BY_PS


def _normalize(value):
    """YAML reads numbers in lists as int; docker always answers with strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return {str(key): [str(item) for item in (items or [])] for key, items in value.items()}
    return value


# --- The simulated daemon ------------------------------------------------------------------------

class SimulatedDocker:
    """Callable backend for docker_tools.use_backend. Records every command it receives."""

    def __init__(self, containers: list[ContainerSpec], now: datetime | None = None):
        self.containers = {spec.name: spec for spec in containers}
        self.now = now or datetime.now(timezone.utc)
        self.commands: list[list[str]] = []
        self.actions: list[tuple[str, str]] = []

    def __call__(self, args: list[str], timeout: int, merge_stderr: bool) -> subprocess.CompletedProcess:
        self.commands.append(list(args))
        try:
            output, code, error = self._answer(args), 0, ""
        except _CommandFailed as failure:
            output, code, error = "", 1, str(failure)
        if merge_stderr:
            return subprocess.CompletedProcess(["docker", *args], code, output + error, None)
        return subprocess.CompletedProcess(["docker", *args], code, output, error)

    def _answer(self, args: list[str]) -> str:
        command, rest = (args[0], args[1:]) if args else ("", [])
        options, names = _split(rest)
        if command == "version":
            return VERSION + "\n"
        if command == "ps":
            return self._ps(include_stopped="-a" in options or "--all" in options)
        if command == "inspect":
            return json.dumps([self._inspect(self._get(name)) for name in names])
        if command == "logs":
            return self._logs(self._get(_last(names)), options.get("--tail") or options.get("-n"))
        if command == "stats":
            return self._stats(names)
        if command in ACTIONS:
            return self._act(command, _last(names))
        raise _CommandFailed(f"docker {command}: not supported by the simulated Docker")

    def _get(self, name: str) -> ContainerSpec:
        if name not in self.containers:
            raise _CommandFailed(f"Error response from daemon: No such container: {name}")
        return self.containers[name]

    # --- Commands ---

    def _ps(self, include_stopped: bool) -> str:
        rows = [_ps_row(spec, self._status_text(spec)) for spec in self.containers.values()
                if include_stopped or spec.is_up]
        return "".join(json.dumps(row) + "\n" for row in rows)

    def _logs(self, spec: ContainerSpec, tail) -> str:
        lines = spec.logs.splitlines()
        count = int(tail) if str(tail or "").isdigit() else DEFAULT_TAIL
        return "\n".join(lines[-count:]) + ("\n" if lines else "")

    def _stats(self, names: list[str]) -> str:
        specs = [self._get(name) for name in names] or [s for s in self.containers.values() if s.is_up]
        return "".join(json.dumps(_stats_row(spec)) + "\n" for spec in specs)

    def _act(self, command: str, name: str) -> str:
        self._get(name)
        self.actions.append((command, name))
        return name + "\n"

    # --- docker inspect ---

    def _inspect(self, spec: ContainerSpec) -> dict:
        return {
            "Name": "/" + spec.name,
            "RestartCount": spec.restart_count,
            "State": self._state(spec),
            "Config": _config(spec),
            "HostConfig": _host_config(spec),
            "Mounts": [_mount(entry) for entry in spec.mounts],
            "NetworkSettings": _network_settings(spec),
        }

    def _state(self, spec: ContainerSpec) -> dict:
        state = {
            "Status": spec.state,
            "ExitCode": spec.exit_code,
            "OOMKilled": spec.oom_killed,
            "Error": spec.error,
            "StartedAt": self._minutes_ago(spec.started_minutes_ago),
            "FinishedAt": ZERO_TIME if spec.is_up else self._minutes_ago(spec.finished_minutes_ago),
        }
        if spec.health:
            state["Health"] = _health(spec)
        return state

    def _status_text(self, spec: ContainerSpec) -> str:
        """The STATUS column of docker ps."""
        if spec.state == "running":
            return f"Up {spec.started_minutes_ago} minutes" + _health_suffix(spec.health)
        if spec.state == "restarting":
            return f"Restarting ({spec.exit_code}) 5 seconds ago"
        if spec.state == "exited":
            return f"Exited ({spec.exit_code}) {spec.finished_minutes_ago} minutes ago"
        return spec.state.capitalize()

    def _minutes_ago(self, minutes: int) -> str:
        return (self.now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")


# --- Building docker's JSON ---------------------------------------------------------------------------

def _split(args: list[str]) -> tuple[dict, list[str]]:
    """Separates options (--tail 80, -a) from positional names."""
    options, names = {}, []
    items = iter(args)
    for arg in items:
        if arg in FLAGS_WITH_VALUE:
            options[arg] = next(items, "")
        elif arg.startswith("-"):
            options[arg] = True
        else:
            names.append(arg)
    return options, names


def _last(names: list[str]) -> str:
    if not names:
        raise _CommandFailed("docker: requires at least 1 argument")
    return names[-1]


def _ps_row(spec: ContainerSpec, status: str) -> dict:
    return {"Names": spec.name, "Image": spec.image, "State": spec.state, "Status": status}


def _stats_row(spec: ContainerSpec) -> dict:
    up = spec.is_up
    return {
        "Name": spec.name,
        "CPUPerc": spec.cpu if up else "0.00%",
        "MemUsage": f"{spec.memory_used} / {_memory_limit(spec)}" if up else "0B / 0B",
        "MemPerc": "2.40%" if up else "0.00%",
        "NetIO": "1.2kB / 800B" if up else "0B / 0B",
        "BlockIO": "0B / 0B",
        "PIDs": "4" if up else "0",
    }


def _memory_limit(spec: ContainerSpec) -> str:
    return f"{spec.memory_mb}MiB" if spec.memory_mb else "7.6GiB"  # no limit: docker shows the host memory


def _health(spec: ContainerSpec) -> dict:
    failed = spec.health == "unhealthy"
    return {
        "Status": spec.health,
        "FailingStreak": max(len(spec.health_log), 3) if failed else 0,
        "Log": [{"ExitCode": 1 if failed else 0, "Output": line} for line in spec.health_log],
    }


def _health_suffix(health: str | None) -> str:
    return {"healthy": " (healthy)", "unhealthy": " (unhealthy)", "starting": " (health: starting)"}.get(health, "")


def _config(spec: ContainerSpec) -> dict:
    return {
        "Image": spec.image,
        "User": spec.user,
        "Env": list(spec.env),
        "Cmd": list(spec.command) or None,
        "Entrypoint": list(spec.entrypoint) or None,
        "Healthcheck": {"Test": list(spec.healthcheck)} if spec.healthcheck else None,
    }


def _host_config(spec: ContainerSpec) -> dict:
    return {
        "Memory": spec.memory_mb * 2**20 if spec.memory_mb else 0,
        "RestartPolicy": {"Name": spec.restart_policy},
        "Privileged": spec.privileged,
        "NetworkMode": spec.network_mode,
        "CapAdd": list(spec.cap_add) or None,
    }


def _mount(entry: str) -> dict:
    source, _, destination = entry.partition(":")
    return {"Type": "bind", "Source": source, "Destination": destination or source}


def _network_settings(spec: ContainerSpec) -> dict:
    ports = {port: [_binding(item) for item in bindings] or None for port, bindings in spec.ports.items()}
    return {"Ports": ports, "Networks": {name: {} for name in spec.networks}}


def _binding(entry: str) -> dict:
    host, _, port = entry.rpartition(":")
    return {"HostIp": host, "HostPort": port}
