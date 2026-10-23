"""docker-compose checks: privileged services, exposed databases, the Docker socket, secrets..."""
from __future__ import annotations

import yaml

from ..i18n import t
from ..redaction import is_sensitive_key
from ..workspace import Workspace, WorkspaceError
from .dockerfile import is_unpinned
from .heuristics import plausible_secret
from .model import Finding, Rule

PRIVILEGED = Rule("DC001", "high", "sec.dc001.title", "sec.dc001.fix")
DOCKER_SOCKET = Rule("DC002", "high", "sec.dc002.title", "sec.dc002.fix")
SECRET_IN_ENV = Rule("DC003", "high", "sec.dc003.title", "sec.dc003.fix")
EXPOSED_DATABASE = Rule("DC004", "high", "sec.dc004.title", "sec.dc004.fix")
UNPINNED_IMAGE = Rule("DC005", "medium", "sec.dc005.title", "sec.dc005.fix")
HOST_NETWORK = Rule("DC006", "medium", "sec.dc006.title", "sec.dc006.fix")
NO_HEALTHCHECK = Rule("DC007", "low", "sec.dc007.title", "sec.dc007.fix")
NO_MEMORY_LIMIT = Rule("DC008", "low", "sec.dc008.title", "sec.dc008.fix")

PATTERNS = ("docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml")
DATABASE_PORTS = {
    5432: "PostgreSQL", 3306: "MySQL/MariaDB", 27017: "MongoDB", 6379: "Redis", 9200: "Elasticsearch",
    5672: "RabbitMQ", 11211: "Memcached", 1433: "SQL Server", 2375: "Docker API", 2379: "etcd",
}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def check(workspace: Workspace, path: str) -> list[Finding]:
    return [finding for name, service in _services(workspace, path).items() for finding in _check_service(path, name, service)]


def _services(workspace: Workspace, path: str) -> dict:
    try:
        data = yaml.safe_load(workspace.text(path)) or {}
    except (WorkspaceError, yaml.YAMLError):
        return {}
    services = data.get("services") if isinstance(data, dict) else None
    return {name: svc for name, svc in (services or {}).items() if isinstance(svc, dict)}


def _check_service(path: str, name: str, service: dict) -> list[Finding]:
    where = t("sec.location.service", path=path, service=name)
    checks = (_privileged, _docker_socket, _secrets, _exposed_databases, _unpinned, _host_network, _healthcheck, _memory)
    return [finding for check_service in checks for finding in check_service(where, service)]


# --- One small check per rule ------------------------------------------------------------------------

def _privileged(where: str, service: dict) -> list[Finding]:
    return [PRIVILEGED.finding(where, "privileged: true")] if service.get("privileged") is True else []


def _docker_socket(where: str, service: dict) -> list[Finding]:
    mounts = [_volume_text(volume) for volume in service.get("volumes") or []]
    return [DOCKER_SOCKET.finding(where, mount) for mount in mounts if "docker.sock" in mount]


def _volume_text(volume) -> str:
    if isinstance(volume, dict):
        return f"{volume.get('source', '')}:{volume.get('target', '')}"
    return str(volume)


def _secrets(where: str, service: dict) -> list[Finding]:
    return [
        SECRET_IN_ENV.finding(where, f"{key}=[REDACTED]")
        for key, value in _environment(service)
        if is_sensitive_key(key) and plausible_secret(value)
    ]


def _environment(service: dict) -> list[tuple[str, str]]:
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return [(str(key), "" if value is None else str(value)) for key, value in env.items()]
    return [(key, value) for key, _, value in (str(item).partition("=") for item in env)]


def _exposed_databases(where: str, service: dict) -> list[Finding]:
    findings = []
    for entry in service.get("ports") or []:
        host_ip, target = parse_port(entry)
        if target in DATABASE_PORTS and host_ip not in LOCAL_HOSTS:
            findings.append(EXPOSED_DATABASE.finding(where, f"{_port_text(entry)} ({DATABASE_PORTS[target]})"))
    return findings


def parse_port(entry) -> tuple[str | None, int | None]:
    """'5432', '5432:5432', '127.0.0.1:5432:5432', '[::1]:5432:5432/tcp', 5432 or the long syntax
    -> (host ip or None, container port or None for ranges)."""
    if isinstance(entry, dict):
        target = str(entry.get("target", ""))
        return entry.get("host_ip"), int(target) if target.isdigit() else None
    parts = str(entry).strip().split("/")[0].rsplit(":", 2)
    host_ip = parts[0].strip("[]") if len(parts) == 3 else None
    return host_ip, int(parts[-1]) if parts[-1].isdigit() else None


def _port_text(entry) -> str:
    return str(entry) if not isinstance(entry, dict) else f"{entry.get('published', '')}:{entry.get('target', '')}"


def _unpinned(where: str, service: dict) -> list[Finding]:
    image = service.get("image")
    if "build" in service or not isinstance(image, str) or not is_unpinned(image):
        return []
    return [UNPINNED_IMAGE.finding(where, f"image: {image}")]


def _host_network(where: str, service: dict) -> list[Finding]:
    return [HOST_NETWORK.finding(where, "network_mode: host")] if service.get("network_mode") == "host" else []


def _healthcheck(where: str, service: dict) -> list[Finding]:
    healthcheck = service.get("healthcheck") or {}
    if not service.get("ports") or (healthcheck and not healthcheck.get("disable")):
        return []
    return [NO_HEALTHCHECK.finding(where)]


def _memory(where: str, service: dict) -> list[Finding]:
    limits = ((service.get("deploy") or {}).get("resources") or {}).get("limits") or {}
    if service.get("mem_limit") or limits.get("memory"):
        return []
    return [NO_MEMORY_LIMIT.finding(where)]
