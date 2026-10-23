"""Security and failure-prevention audit.

One small module per area (Dockerfile, compose, running containers, logs, repository secrets);
each rule has an id (DF002...), a severity and a translated title and fix.
"""
from .audit import as_json, audit, docker_available, format_report, severity_label
from .model import NEVER, SEVERITIES, Finding, Rule, count_by_severity, fails

__all__ = [
    "NEVER", "SEVERITIES", "Finding", "Rule", "as_json", "audit", "count_by_severity",
    "docker_available", "fails", "format_report", "severity_label",
]
