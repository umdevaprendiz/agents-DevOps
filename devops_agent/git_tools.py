"""Git access through the CLI, always with argument lists (never a shell).

Agent proposals are written with plumbing commands (a temporary index + commit-tree),
so the operator's working tree, index and current branch stay untouched until /apply.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .i18n import t

TIMEOUT = 60
PUSH_TIMEOUT = 180
DEFAULT_MODE = "100644"
AGENT_NAME = "DevOps Agent"
AGENT_EMAIL = "devops-agent@users.noreply.localhost"
AGENT_IDENTITY = {
    "GIT_AUTHOR_NAME": AGENT_NAME,
    "GIT_AUTHOR_EMAIL": AGENT_EMAIL,
    "GIT_COMMITTER_NAME": AGENT_NAME,
    "GIT_COMMITTER_EMAIL": AGENT_EMAIL,
}


class GitError(Exception):
    """Any failure running a git command."""


# --- Execution ------------------------------------------------------------------------------------

def _git(root: Path, args: list[str], data: bytes | None = None, env: dict | None = None, timeout: int = TIMEOUT) -> str:
    proc = _invoke(root, args, data, env, timeout)
    if proc.returncode != 0:
        raise GitError(_error_text(proc, args))
    # Decoded by hand: text mode would translate line endings and corrupt CRLF files.
    return proc.stdout.decode("utf-8", errors="replace")


def _succeeds(root: Path, args: list[str]) -> bool:
    return _invoke(root, args, None, None, TIMEOUT).returncode == 0


def _invoke(root: Path, args: list[str], data, env, timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, input=data, capture_output=True, env=_environment(env), timeout=timeout
        )
    except FileNotFoundError as error:
        raise GitError(t("git.cli_missing")) from error
    except subprocess.TimeoutExpired as error:
        raise GitError(t("git.timeout", command=args[0], seconds=timeout)) from error


def _environment(extra: dict | None) -> dict:
    # Never wait for a credential prompt that nobody will answer.
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(extra or {})}


def _error_text(proc: subprocess.CompletedProcess, args: list[str]) -> str:
    message = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
    return message or t("git.exit_code", command=args[0], code=proc.returncode)


# --- Reading ----------------------------------------------------------------------------------------

def is_repo(root: Path) -> bool:
    try:
        return _succeeds(root, ["rev-parse", "--is-inside-work-tree"])
    except GitError:
        return False


def top_level(root: Path) -> Path:
    return Path(_git(root, ["rev-parse", "--show-toplevel"]).strip()).resolve()


def current_branch(root: Path) -> str:
    return _git(root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def head_commit(root: Path) -> str:
    return _git(root, ["rev-parse", "HEAD"]).strip()


def status(root: Path) -> str:
    return _git(root, ["status", "--short", "--branch"]).strip()


def log(root: Path, limit: int = 10) -> str:
    return _git(root, ["log", f"-n{limit}", "--date=short", "--format=%h %ad %an: %s"]).strip()


def working_diff(root: Path, pathspecs: list[str]) -> str:
    return _git(root, ["diff", "--no-color", "--", *pathspecs]).strip()


def listed_files(root: Path) -> list[str]:
    """Tracked plus new files, respecting .gitignore (paths relative to root)."""
    output = _git(root, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    return sorted({name for name in output.split("\0") if name})


def tracked_files(root: Path) -> list[str]:
    """Files committed or staged (paths relative to root)."""
    return sorted(name for name in _git(root, ["ls-files", "-z"]).split("\0") if name)


def is_ignored(root: Path, path: str) -> bool:
    return _succeeds(root, ["check-ignore", "-q", "--", path])


def read_blob(root: Path, ref: str, path: str) -> str | None:
    """File content at a commit, or None when the file does not exist there."""
    if not _succeeds(root, ["cat-file", "-e", f"{ref}:{path}"]):
        return None
    return _git(root, ["cat-file", "blob", f"{ref}:{path}"])


def file_mode(root: Path, ref: str, path: str) -> str:
    entry = _git(root, ["ls-tree", ref, "--", path]).strip()
    return entry.split(" ", 1)[0] if entry else DEFAULT_MODE


def branches(root: Path, prefix: str) -> list[str]:
    """Local branches under a prefix, newest first."""
    output = _git(root, ["for-each-ref", "--sort=-committerdate", "--format=%(refname:short)", f"refs/heads/{prefix}"])
    return [line for line in output.splitlines() if line]


def commit_of(root: Path, ref: str) -> str:
    return _git(root, ["rev-parse", ref]).strip()


def message_of(root: Path, ref: str) -> str:
    return _git(root, ["log", "-1", "--format=%B", ref]).strip()


def diff_commits(root: Path, old: str, new: str) -> str:
    return _git(root, ["diff", "--no-color", old, new]).strip()


def is_ancestor(root: Path, commit: str, ref: str = "HEAD") -> bool:
    return _succeeds(root, ["merge-base", "--is-ancestor", commit, ref])


def last_merge(root: Path, mark: str) -> str | None:
    return _git(root, ["log", "--merges", "-n1", f"--grep={mark}", "--format=%H"]).strip() or None


def is_reverted(root: Path, commit: str) -> bool:
    return bool(_git(root, ["log", "-n1", f"--grep=This reverts commit {commit}", "--format=%H"]).strip())


def has_remote(root: Path, remote: str = "origin") -> bool:
    return remote in _git(root, ["remote"]).split()


# --- Agent commits (plumbing: never touches the working tree) ------------------------------------------

def commit_files(root: Path, base: str, files: dict[str, str], message: str) -> str:
    """Creates a commit on top of base with the given file contents; returns its hash."""
    with tempfile.TemporaryDirectory() as folder:
        index = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
        _git(root, ["read-tree", base], env=index)
        for path, content in files.items():
            _stage(root, base, path, content, index)
        tree = _git(root, ["write-tree"], env=index).strip()
    return _git(root, ["commit-tree", tree, "-p", base, "-F", "-"], data=message.encode("utf-8"), env=AGENT_IDENTITY).strip()


def _stage(root: Path, base: str, path: str, content: str, index: dict) -> None:
    blob = _git(root, ["hash-object", "-w", "--stdin"], data=content.encode("utf-8")).strip()
    mode = file_mode(root, base, path)
    _git(root, ["update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}"], env=index)


def create_branch(root: Path, name: str, commit: str) -> None:
    _git(root, ["branch", name, commit])


def delete_branch(root: Path, name: str, force: bool = False) -> None:
    _git(root, ["branch", "-D" if force else "-d", name])


# --- Operator decisions ----------------------------------------------------------------------------------

def merge(root: Path, branch: str, message: str) -> None:
    try:
        _git(root, ["merge", "--no-ff", "--no-edit", "-m", message, branch])
    except GitError:
        _abort(root, "merge")
        raise


def revert_merge(root: Path, commit: str) -> None:
    try:
        _git(root, ["revert", "--no-edit", "-m", "1", commit])
    except GitError:
        _abort(root, "revert")
        raise


def _abort(root: Path, operation: str) -> None:
    """Leaves the repository as it was after a conflict (ignored when nothing is in progress)."""
    _invoke(root, [operation, "--abort"], None, None, TIMEOUT)


def push(root: Path, branch: str, remote: str = "origin") -> None:
    _git(root, ["push", "-u", remote, branch], timeout=PUSH_TIMEOUT)
