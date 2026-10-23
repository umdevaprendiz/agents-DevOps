"""Rules and findings of the security audit."""
from __future__ import annotations

from dataclasses import dataclass

from ..i18n import t

SEVERITIES = ("high", "medium", "low")
NEVER = "never"
_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    title_key: str
    fix_key: str

    def finding(self, location: str, detail: str = "") -> Finding:
        return Finding(self, location, detail)


@dataclass(frozen=True)
class Finding:
    rule: Rule
    location: str
    detail: str = ""

    @property
    def severity(self) -> str:
        return self.rule.severity

    def title(self) -> str:
        return t(self.rule.title_key)

    def fix(self) -> str:
        return t(self.rule.fix_key)

    def as_dict(self) -> dict:
        return {
            "rule": self.rule.id,
            "severity": self.severity,
            "location": self.location,
            "title": self.title(),
            "detail": self.detail,
            "fix": self.fix(),
        }


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Most severe first, then by rule and location, so reports are stable."""
    return sorted(findings, key=lambda f: (_RANK[f.severity], f.rule.id, f.location))


def count_by_severity(findings: list[Finding]) -> dict[str, int]:
    return {severity: sum(1 for f in findings if f.severity == severity) for severity in SEVERITIES}


def fails(findings: list[Finding], threshold: str) -> bool:
    """True when a finding is at least as severe as the threshold (`never` never fails)."""
    if threshold == NEVER:
        return False
    return any(_RANK[f.severity] <= _RANK[threshold] for f in findings)
