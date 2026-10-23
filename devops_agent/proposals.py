"""Change proposals: each suggestion from the agent becomes one commit on its own branch.

The operator reviews it (/diff, /explain) and decides: /apply merges it into the current
branch, /pr pushes it and opens a pull request, /discard deletes it. Nothing touches the
operator's working tree before /apply.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import git_tools as git
from .i18n import t
from .redaction import MASK, redact
from .workspace import Workspace

BRANCH_PREFIX = "agent/"
APPLY_MARK = "devops-agent: apply"
MAX_TITLE = 72
MAX_SLUG = 40
_LINE_NUMBER_RE = re.compile(r"(?m)^[ \t]*\d+\| ?")


class ProposalError(Exception):
    """A proposal that cannot be created, found or applied."""


@dataclass(frozen=True)
class Edit:
    path: str
    old_text: str
    new_text: str


@dataclass(frozen=True)
class Proposal:
    branch: str
    commit: str
    title: str
    explanation: str

    @property
    def id(self) -> str:
        return self.branch.rsplit("-", 1)[-1]


# --- Building the new file contents ------------------------------------------------------------------

def parse_edits(raw) -> list[Edit]:
    """Accepts a list of dicts, one dict, or a JSON string (small models send all three)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ProposalError(t("proposal.bad_edits")) from error
    items = [raw] if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise ProposalError(t("proposal.no_edits"))
    return [_edit(item) for item in items]


def _edit(item) -> Edit:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise ProposalError(t("proposal.bad_edits"))
    return Edit(item["path"], str(item.get("old_text") or ""), str(item.get("new_text") or ""))


def apply_edit(current: str | None, edit: Edit) -> str:
    """New content of one file after the edit."""
    _check_secrets(edit)
    if edit.old_text == "":
        if current is not None:
            raise ProposalError(t("proposal.file_exists", path=edit.path))
        return edit.new_text
    if current is None:
        raise ProposalError(t("proposal.file_missing", path=edit.path))
    old, new = _match_line_endings(current, edit.old_text, edit.new_text)
    return _replace_once(current, old, new, edit.path)


def _check_secrets(edit: Edit) -> None:
    if MASK in edit.old_text:
        raise ProposalError(t("proposal.redacted_old", path=edit.path))
    if MASK in edit.new_text or redact(edit.new_text) != edit.new_text:
        raise ProposalError(t("proposal.secret_new", path=edit.path))


def _match_line_endings(current: str, old: str, new: str) -> tuple[str, str]:
    if "\r\n" in current and "\r\n" not in old:
        return old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    return old, new


def _replace_once(content: str, old: str, new: str, path: str) -> str:
    # Second attempt without "12| " prefixes: models often copy them from read_file.
    for candidate_old, candidate_new in ((old, new), (_strip_numbers(old), _strip_numbers(new))):
        count = content.count(candidate_old)
        if count == 1:
            return content.replace(candidate_old, candidate_new, 1)
        if count > 1:
            raise ProposalError(t("proposal.ambiguous", path=path, count=count))
    raise ProposalError(t("proposal.not_found", path=path))


def _strip_numbers(text: str) -> str:
    return _LINE_NUMBER_RE.sub("", text)


def _title(title: str) -> str:
    first_line = (title or "").strip().splitlines()[0] if (title or "").strip() else "change"
    return first_line[:MAX_TITLE]


def _branch_name(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:MAX_SLUG].strip("-") or "change"
    return f"{BRANCH_PREFIX}{slug}-{uuid.uuid4().hex[:6]}"


# --- Store ----------------------------------------------------------------------------------------

class ProposalStore:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    # Creating (called by the propose_change tool)

    def create(self, title: str, explanation: str, edits) -> Proposal:
        root = self._repo()
        files = self._new_contents(root, parse_edits(edits))
        message = f"{_title(title)}\n\n{(explanation or '').strip()}\n"
        commit = git.commit_files(root, git.head_commit(root), files, message)
        branch = _branch_name(_title(title))
        git.create_branch(root, branch, commit)
        return Proposal(branch, commit, _title(title), (explanation or "").strip())

    def _new_contents(self, root: Path, edits: list[Edit]) -> dict[str, str]:
        files: dict[str, str] = {}
        for edit in edits:
            path = self._git_path(root, edit.path)
            current = files[path] if path in files else git.read_blob(root, "HEAD", path)
            files[path] = apply_edit(current, edit)
        return files

    def _git_path(self, root: Path, path: str) -> str:
        """Path relative to the repository root (the workspace may be a subfolder)."""
        return self.workspace.resolve(path).relative_to(root).as_posix()

    # Reading

    def pending(self) -> list[Proposal]:
        """Proposals not merged into the current branch yet, newest first."""
        root = self._repo()
        proposals = [self._load(root, branch) for branch in git.branches(root, BRANCH_PREFIX)]
        return [proposal for proposal in proposals if not git.is_ancestor(root, proposal.commit)]

    def get(self, ref: str | None = None) -> Proposal:
        proposals = self.pending()
        if not proposals:
            raise ProposalError(t("proposal.none"))
        if not ref:
            return proposals[0]
        for proposal in proposals:
            if ref in (proposal.id, proposal.branch):
                return proposal
        raise ProposalError(t("proposal.unknown", ref=ref))

    def diff(self, proposal: Proposal) -> str:
        return git.diff_commits(self._repo(), f"{proposal.commit}^", proposal.commit)

    def current_branch(self) -> str:
        return git.current_branch(self._repo())

    def _load(self, root: Path, branch: str) -> Proposal:
        title, _, body = git.message_of(root, branch).partition("\n")
        return Proposal(branch, git.commit_of(root, branch), title.strip(), body.strip())

    # Operator decisions

    def apply(self, proposal: Proposal) -> None:
        root = self._repo()
        git.merge(root, proposal.branch, f"{APPLY_MARK} {proposal.branch}\n\n{proposal.title}")
        git.delete_branch(root, proposal.branch)

    def discard(self, proposal: Proposal) -> None:
        git.delete_branch(self._repo(), proposal.branch, force=True)

    def undo_last(self) -> str:
        """Reverts the last applied proposal with a new commit (history is kept)."""
        root = self._repo()
        merge = git.last_merge(root, APPLY_MARK)
        if merge is None:
            raise ProposalError(t("proposal.nothing_to_undo"))
        if git.is_reverted(root, merge):
            raise ProposalError(t("proposal.already_undone", commit=merge[:8]))
        git.revert_merge(root, merge)
        return merge[:8]

    def open_pull_request(self, proposal: Proposal) -> str:
        """Pushes the branch and opens a PR with the GitHub CLI when it is available."""
        root = self._repo()
        if not git.has_remote(root):
            raise ProposalError(t("proposal.no_remote"))
        base = git.current_branch(root)
        git.push(root, proposal.branch)
        if shutil.which("gh") is None:
            return t("proposal.pushed_no_gh", branch=proposal.branch, base=base)
        return _gh_pull_request(root, proposal, base)

    def _repo(self) -> Path:
        if not git.is_repo(self.workspace.root):
            raise ProposalError(t("proposal.not_repo"))
        return git.top_level(self.workspace.root)


def _gh_pull_request(root: Path, proposal: Proposal, base: str) -> str:
    command = ["gh", "pr", "create", "--head", proposal.branch, "--base", base,
               "--title", proposal.title, "--body", proposal.explanation or proposal.title]
    proc = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ProposalError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()
