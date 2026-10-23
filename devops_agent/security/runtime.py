"""Checks on running containers (from docker inspect)."""
from __future__ import annotations

from .. import docker_tools as dk
from ..i18n import t
from .compose import DATABASE_PORTS
from .dockerfile import ROOT_USERS
from .model import Finding, Rule

PRIVILEGED = Rule("RC001", "high", "sec.rc001.title", "sec.rc001.fix")
DOCKER_SOCKET = Rule("RC002", "high", "sec.rc002.title", "sec.rc002.fix")
EXPOSED_DATABASE = Rule("RC003", "high", "sec.rc003.title", "sec.rc003.fix")
RUNS_AS_ROOT = Rule("RC004", "medium", "sec.rc004.title", "sec.rc004.fix")
HOST_NETWORK = Rule("RC005", "medium", "sec.rc005.title", "sec.rc005.fix")
NO_MEMORY_LIMIT = Rule("RC006", "low", "sec.rc006.title", "sec.rc006.fix")

PUBLIC_HOSTS = {"", "0.0.0.0", "::"}


def running_containers() -> list[dict]:
    names = [container["name"] for container in dk.list_containers(include_stopped=False)]
    return dk.inspect_containers(names)


def check(containers: list[dict]) -> list[Finding]:
    return [finding for info in containers for finding in _check_container(info)]


def _check_container(info: dict) -> list[Finding]:
    where = t("sec.location.container", name=info["name"])
    checks = (_privileged, _docker_socket, _exposed_databases, _root, _host_network, _memory)
    return [finding for check_container in checks for finding in check_container(where, info)]


def _privileged(where: str, info: dict) -> list[Finding]:
    return [PRIVILEGED.finding(where, "Privileged: true")] if info.get("privileged") else []


def _docker_socket(where: str, info: dict) -> list[Finding]:
    return [DOCKER_SOCKET.finding(where, mount) for mount in info.get("mounts") or [] if "docker.sock" in mount]


def _exposed_databases(where: str, info: dict) -> list[Finding]:
    findings = []
    for port, bindings in (info.get("ports") or {}).items():
        target = _port_number(port)
        public = [binding for binding in bindings or [] if _host_of(binding) in PUBLIC_HOSTS]
        if target in DATABASE_PORTS and public:
            findings.append(EXPOSED_DATABASE.finding(where, f"{public[0]} -> {port} ({DATABASE_PORTS[target]})"))
    return findings


def _port_number(port: str) -> int | None:
    number = port.split("/")[0]
    return int(number) if number.isdigit() else None


def _host_of(binding: str) -> str:
    return binding.rsplit(":", 1)[0].strip("[]")


def _root(where: str, info: dict) -> list[Finding]:
    user = (info.get("user") or "").lower()
    return [RUNS_AS_ROOT.finding(where, f"User: {user or 'root'}")] if not user or user in ROOT_USERS else []


def _host_network(where: str, info: dict) -> list[Finding]:
    return [HOST_NETWORK.finding(where, "NetworkMode: host")] if info.get("network_mode") == "host" else []


def _memory(where: str, info: dict) -> list[Finding]:
    return [NO_MEMORY_LIMIT.finding(where)] if info.get("memory_limit_mb") is None else []
