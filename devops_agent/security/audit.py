"""Security and failure-prevention audit: deterministic and fast, no model involved."""
from __future__ import annotations

import json

from .. import docker_tools as dk
from ..i18n import t
from ..workspace import Workspace
from . import compose, dockerfile, logs, runtime, secrets
from .model import Finding, count_by_severity, sort_findings

SEVERITY_LABELS = {"high": "sec.severity.high", "medium": "sec.severity.medium", "low": "sec.severity.low"}


def audit(workspace: Workspace | None = None, docker: bool = True) -> list[Finding]:
    findings = _project_findings(workspace) if workspace is not None else []
    if docker:
        findings += _docker_findings()
    return sort_findings(findings)


def docker_available() -> bool:
    try:
        dk.server_version()
        return True
    except dk.DockerError:
        return False


def _project_findings(workspace: Workspace) -> list[Finding]:
    checks = ((dockerfile.check, dockerfile.PATTERNS), (compose.check, compose.PATTERNS))
    findings = [f for check, patterns in checks for path in _paths(workspace, patterns) for f in check(workspace, path)]
    findings += secrets.check(workspace)
    return findings + [f for source, lines in logs.file_sources(workspace) for f in logs.check(source, lines)]


def _paths(workspace: Workspace, patterns: tuple[str, ...]) -> list[str]:
    return sorted({path for pattern in patterns for path in workspace.paths(pattern)})


def _docker_findings() -> list[Finding]:
    try:
        findings = runtime.check(runtime.running_containers())
        return findings + [f for source, lines in logs.container_sources() for f in logs.check(source, lines)]
    except dk.DockerError:
        return []


# --- Output -----------------------------------------------------------------------------------------

def severity_label(severity: str) -> str:
    return t(SEVERITY_LABELS[severity])


def format_report(findings: list[Finding]) -> str:
    """Plain-text report (what the model reads)."""
    if not findings:
        return t("sec.report.none")
    lines = [t("sec.report.header", **count_by_severity(findings))]
    for finding in findings:
        lines.append(f"[{severity_label(finding.severity)}] {finding.rule.id} · {finding.location} · {finding.title()}")
        if finding.detail:
            lines.append(f"    {finding.detail}")
        lines.append(f"    {t('sec.report.fix', fix=finding.fix())}")
    return "\n".join(lines)


def as_json(findings: list[Finding]) -> str:
    report = {"summary": count_by_severity(findings), "findings": [finding.as_dict() for finding in findings]}
    return json.dumps(report, ensure_ascii=False, indent=2)
