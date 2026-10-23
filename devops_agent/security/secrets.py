"""Secrets in the repository: hard-coded values, committed secret files and secret files git would commit."""
from __future__ import annotations

from pathlib import PurePosixPath

from .. import git_tools as git
from ..redaction import redact
from ..workspace import Workspace, WorkspaceError, is_secret
from .heuristics import looks_like_secret
from .model import Finding, Rule

HARDCODED = Rule("SC001", "high", "sec.sc001.title", "sec.sc001.fix")
COMMITTED_SECRET_FILE = Rule("SC002", "high", "sec.sc002.title", "sec.sc002.fix")
UNIGNORED_SECRET_FILE = Rule("SC003", "high", "sec.sc003.title", "sec.sc003.fix")

SCANNED_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".go", ".java", ".kt", ".rb", ".php", ".cs", ".sh", ".ps1",
    ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties", ".tf", ".tfvars", ".xml",
}
SCANNED_NAMES = {".env.example", ".env.sample", ".env.template"}
# Tests and docs are full of fake credentials on purpose.
SKIPPED_DIRS = {"test", "tests", "spec", "specs", "fixtures", "testdata", "__tests__", "examples", "docs"}
TEST_NAME_MARKERS = ("test_", "_test.", ".test.", ".spec.")
MAX_PER_FILE = 3
MAX_FINDINGS = 50
DETAIL_CHARS = 160


def check(workspace: Workspace) -> list[Finding]:
    return _hardcoded(workspace) + _secret_files(workspace)


def _hardcoded(workspace: Workspace) -> list[Finding]:
    findings: list[Finding] = []
    for path in workspace.paths("*"):
        if len(findings) >= MAX_FINDINGS:
            break
        if scannable(path):
            findings += _file_secrets(workspace, path)
    return findings[:MAX_FINDINGS]


def scannable(path: str) -> bool:
    pure = PurePosixPath(path)
    if any(part.lower() in SKIPPED_DIRS for part in pure.parts[:-1]):
        return False
    if any(marker in pure.name for marker in TEST_NAME_MARKERS):
        return False
    return pure.suffix.lower() in SCANNED_SUFFIXES or pure.name in SCANNED_NAMES or pure.name.startswith("Dockerfile")


def _file_secrets(workspace: Workspace, path: str) -> list[Finding]:
    try:
        lines = workspace.text(path).splitlines()
    except WorkspaceError:
        return []
    hits = [(number, line) for number, line in enumerate(lines, start=1) if looks_like_secret(line)][:MAX_PER_FILE]
    return [HARDCODED.finding(f"{path}:{number}", redact(line.strip())[:DETAIL_CHARS]) for number, line in hits]


def _secret_files(workspace: Workspace) -> list[Finding]:
    """Secret files are only listed by name here, never opened."""
    if not git.is_repo(workspace.root):
        return []
    tracked = set(git.tracked_files(workspace.root))
    committed = [COMMITTED_SECRET_FILE.finding(path) for path in sorted(tracked) if is_secret(PurePosixPath(path).name)]
    exposed = [
        UNIGNORED_SECRET_FILE.finding(path)
        for path in workspace.secret_files()
        if path not in tracked and not git.is_ignored(workspace.root, path)
    ]
    return committed + exposed
