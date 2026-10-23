"""Read-only access to the project the agent works on (the workspace).

Paths are confined to the workspace root, secret files (.env, private keys...) are never
opened, and binary or huge files are refused. Outputs are still redacted by the agent.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path, PurePosixPath

from . import git_tools as git
from .i18n import t

DEFAULT_LINES = 200
MAX_LINES = 500
MAX_FILE_BYTES = 512_000
MAX_LISTED = 300
MAX_MATCHES = 60
MAX_LOG = 50
MATCH_CHARS = 200
SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", "dist", "build"}
SECRET_NAMES = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", ".git-credentials", ".netrc", ".npmrc", ".pypirc",
)
PUBLIC_NAMES = (".env.example", ".env.sample", ".env.template", "*.pub")
LOG_PATTERNS = ("*.log", "*.log.[0-9]", "*.err")
MAX_LOG_FILES = 20
TAIL_BYTES = 256_000


class WorkspaceError(Exception):
    """A path outside the workspace, a secret file, or a file that cannot be read."""


def is_secret(name: str) -> bool:
    if any(fnmatch.fnmatch(name, pattern) for pattern in PUBLIC_NAMES):
        return False
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_NAMES)


def _forbidden(relative: PurePosixPath | Path) -> bool:
    return ".git" in relative.parts or is_secret(relative.name)


def _inside(target: Path, root: Path) -> bool:
    return target == root or root in target.parents


def _clamp(value, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def _compile(pattern: str) -> re.Pattern[str]:
    """Regular expression, or a literal search when the pattern is not valid regex."""
    try:
        return re.compile(pattern)
    except re.error:
        return re.compile(re.escape(pattern))


def _secret_pathspecs() -> list[str]:
    return [".", *(f":(exclude,glob)**/{name}" for name in SECRET_NAMES)]


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        """Absolute path inside the workspace; refuses escapes and secret files."""
        target = (self.root / path).resolve()
        if not _inside(target, self.root):
            raise WorkspaceError(t("workspace.outside", path=path))
        if _forbidden(target.relative_to(self.root)):
            raise WorkspaceError(t("workspace.secret", path=path))
        return target

    def relative(self, target: Path) -> str:
        return target.relative_to(self.root).as_posix()

    # --- Tools ---------------------------------------------------------------------------------

    def list_files(self, pattern: str = "*") -> str:
        matches = self.paths(pattern)
        if not matches:
            return t("workspace.no_files")
        shown = "\n".join(matches[:MAX_LISTED])
        extra = len(matches) - MAX_LISTED
        return shown + ("\n" + t("workspace.more", count=extra) if extra > 0 else "")

    def read_file(self, path: str, start_line=1, max_lines=DEFAULT_LINES) -> str:
        target = self.resolve(path)
        lines = self._read_text(target, path).splitlines()
        first = max(1, int(start_line))
        chunk = lines[first - 1 : first - 1 + _clamp(max_lines, 1, MAX_LINES)]
        header = t("workspace.file_header", path=self.relative(target), first=first, last=first + len(chunk) - 1, total=len(lines))
        return "\n".join([header, *(f"{number}| {line}" for number, line in enumerate(chunk, start=first))])

    def search(self, pattern: str, glob: str = "*") -> str:
        regex = _compile(pattern)
        matches = []
        for relative in self.paths(glob):
            matches += self._matches(relative, regex)
            if len(matches) >= MAX_MATCHES:
                break
        return "\n".join(matches[:MAX_MATCHES]) or t("workspace.no_matches")

    def git_status(self) -> str:
        return git.status(self.root)

    def git_log(self, limit=10) -> str:
        return git.log(self.root, _clamp(limit, 1, MAX_LOG))

    def git_diff(self, path: str | None = None) -> str:
        """Uncommitted changes, never including secret files."""
        specs = [self.relative(self.resolve(path))] if path else _secret_pathspecs()
        return git.working_diff(self.root, specs) or t("workspace.no_changes")

    # --- Files ---------------------------------------------------------------------------------

    def paths(self, pattern: str = "*") -> list[str]:
        """Every visible file matching a glob (on the full path or on the file name)."""
        return [path for path in self._files() if _matches_glob(path, pattern)]

    def text(self, path: str) -> str:
        """Whole content of a project text file (same limits as read_file)."""
        return self._read_text(self.resolve(path), path)

    def secret_files(self) -> list[str]:
        """Names of secret files on disk (.env, keys...). They are listed, never read."""
        return sorted(path for path in self._walk() if is_secret(PurePosixPath(path).name))

    def log_files(self) -> list[str]:
        """Log files anywhere in the project, including git-ignored ones (logs usually are)."""
        found = [path for path in self._walk() if any(_matches_glob(path, p) for p in LOG_PATTERNS)]
        return sorted(path for path in found if not _forbidden(PurePosixPath(path)))[:MAX_LOG_FILES]

    def tail_lines(self, path: str, max_bytes: int = TAIL_BYTES) -> list[str]:
        """Last lines of a text file, even a huge one."""
        target = self.resolve(path)
        size = target.stat().st_size
        with target.open("rb") as file:
            file.seek(max(0, size - max_bytes))
            data = file.read()
        if b"\0" in data:
            raise WorkspaceError(t("workspace.binary", path=path))
        lines = data.decode("utf-8", errors="replace").splitlines()
        return lines[1:] if size > max_bytes else lines  # the first line may be cut in half

    def _files(self) -> list[str]:
        names = git.listed_files(self.root) if git.is_repo(self.root) else self._walk()
        return sorted(name for name in names if not _forbidden(PurePosixPath(name)))

    def _walk(self) -> list[str]:
        found = []
        for folder, dirs, files in os.walk(self.root):
            dirs[:] = [name for name in dirs if name not in SKIPPED_DIRS]
            found += [self.relative(Path(folder) / name) for name in files]
        return found

    def _read_text(self, target: Path, path: str) -> str:
        if not target.is_file():
            raise WorkspaceError(t("workspace.not_found", path=path))
        if target.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(t("workspace.too_big", path=path, size=MAX_FILE_BYTES // 1024))
        data = target.read_bytes()
        if b"\0" in data:
            raise WorkspaceError(t("workspace.binary", path=path))
        return data.decode("utf-8", errors="replace")

    def _matches(self, relative: str, regex: re.Pattern[str]) -> list[str]:
        try:
            text = self._read_text(self.root / relative, relative)
        except (WorkspaceError, OSError):
            return []
        return [
            f"{relative}:{number}: {line.strip()[:MATCH_CHARS]}"
            for number, line in enumerate(text.splitlines(), start=1)
            if regex.search(line)
        ]


def _matches_glob(path: str, pattern: str) -> bool:
    # Case-sensitive on every OS: on Windows "dockerfile.py" must not match "Dockerfile.*".
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(PurePosixPath(path).name, pattern)
