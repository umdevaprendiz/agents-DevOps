"""Security signals in logs: brute force, attack probes and secrets printed in clear text."""
from __future__ import annotations

import re
from collections import Counter

from .. import docker_tools as dk
from ..i18n import t
from ..redaction import redact
from ..workspace import Workspace, WorkspaceError
from .heuristics import looks_like_secret
from .model import Finding, Rule

BRUTE_FORCE = Rule("LG001", "high", "sec.lg001.title", "sec.lg001.fix")
ATTACK_PROBES = Rule("LG002", "medium", "sec.lg002.title", "sec.lg002.fix")
SECRET_IN_LOGS = Rule("LG003", "high", "sec.lg003.title", "sec.lg003.fix")

AUTH_FAILURE_RE = re.compile(
    r"(?i)failed password|authentication failed|invalid (?:user|password|credentials)|login failed"
    r"|unauthori[sz]ed|\s401\s"
)
ATTACK_RE = re.compile(
    r"(?i)\.\./|%2e%2e%2f|/etc/passwd|union\s+(?:all\s+)?select|'\s*or\s+'?1'?\s*=\s*'?1|<script"
    r"|/wp-admin|/wp-login|/\.env\b|/\.git/|/phpmyadmin"
)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
BRUTE_FORCE_THRESHOLD = 10
TOP_SOURCES = 3
EXAMPLE_CHARS = 160


def check(source: str, lines: list[str]) -> list[Finding]:
    found = (_brute_force(source, lines), _attack_probes(source, lines), _printed_secrets(source, lines))
    return [finding for finding in found if finding]


def _brute_force(source: str, lines: list[str]) -> Finding | None:
    failures = [line for line in lines if AUTH_FAILURE_RE.search(line)]
    if len(failures) < BRUTE_FORCE_THRESHOLD:
        return None
    return BRUTE_FORCE.finding(source, t("sec.detail.auth", count=len(failures), sources=_top_sources(failures)))


def _top_sources(lines: list[str]) -> str:
    counts = Counter(ip for line in lines for ip in IP_RE.findall(line))
    return ", ".join(f"{ip} ({count})" for ip, count in counts.most_common(TOP_SOURCES)) or "-"


def _attack_probes(source: str, lines: list[str]) -> Finding | None:
    hits = [line for line in lines if ATTACK_RE.search(line)]
    if not hits:
        return None
    return ATTACK_PROBES.finding(source, t("sec.detail.attacks", count=len(hits), example=_example(hits[-1])))


def _printed_secrets(source: str, lines: list[str]) -> Finding | None:
    leaks = [line for line in lines if looks_like_secret(line)]
    if not leaks:
        return None
    return SECRET_IN_LOGS.finding(source, t("sec.detail.secrets", count=len(leaks), example=_example(leaks[-1])))


def _example(line: str) -> str:
    return redact(line.strip())[:EXAMPLE_CHARS]


# --- Where the lines come from ----------------------------------------------------------------------

def container_sources() -> list[tuple[str, list[str]]]:
    sources = []
    for container in dk.list_containers(include_stopped=False):
        try:
            text = dk.container_logs(container["name"], tail=dk.MAX_LOG_LINES)
        except dk.DockerError:
            continue
        sources.append((t("sec.location.container", name=container["name"]), text.splitlines()))
    return sources


def file_sources(workspace: Workspace) -> list[tuple[str, list[str]]]:
    sources = []
    for path in workspace.log_files():
        try:
            sources.append((path, workspace.tail_lines(path)))
        except (WorkspaceError, OSError):
            continue
    return sources
