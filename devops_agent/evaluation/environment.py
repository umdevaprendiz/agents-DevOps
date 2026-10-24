"""A throwaway copy of a scenario: its files in a temporary git repository and its containers in a
simulated Docker. Nothing touches the operator's project or the real Docker daemon."""
from __future__ import annotations

import tempfile
from contextlib import ExitStack
from pathlib import Path

from .. import docker_tools as dk
from .. import git_tools as git
from ..proposals import Proposal, ProposalError, ProposalStore
from ..tools import Toolbox, build_toolbox
from ..workspace import Workspace
from .scenario import Scenario
from .simulator import SimulatedDocker

GIT_CONFIG = {
    "user.name": "DevOps Agent Evaluation",
    "user.email": "devops-agent-eval@users.noreply.localhost",
    "core.autocrlf": "false",
    "commit.gpgsign": "false",
}


class RecordingStore(ProposalStore):
    """Remembers the order in which the agent created its proposals (git dates have one-second precision)."""

    def __init__(self, workspace: Workspace):
        super().__init__(workspace)
        self.created: list[Proposal] = []

    def create(self, title: str, explanation: str, edits) -> Proposal:
        proposal = super().create(title, explanation, edits)
        self.created.append(proposal)
        return proposal


class Environment:
    """Context manager: everything exists only inside the `with` block."""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.docker = SimulatedDocker(list(scenario.containers))
        self._stack = ExitStack()

    def __enter__(self) -> Environment:
        try:
            self._create()
        except BaseException:
            self._stack.close()
            raise
        return self

    def __exit__(self, *exc_info) -> None:
        self._stack.close()

    def _create(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="devops-agent-eval-", ignore_cleanup_errors=True)
        self.root = Path(self._stack.enter_context(folder))
        write_files(self.root, self.scenario.files)
        git.init(self.root, config=GIT_CONFIG)
        git.commit_all(self.root, f"scenario {self.scenario.id}")
        self.workspace = Workspace(self.root)
        self.proposals = RecordingStore(self.workspace)
        self.tools: Toolbox = build_toolbox(self.workspace, self.proposals)
        self._stack.enter_context(dk.use_backend(self.docker))

    def apply_proposals(self) -> int:
        """Merges every proposal, oldest first, like an operator accepting all of them.
        A proposal that conflicts with an earlier one is skipped. Returns how many were merged."""
        merged = 0
        for proposal in self.proposals.created:
            try:
                self.proposals.apply(proposal)
                merged += 1
            except (ProposalError, git.GitError):
                continue
        return merged

    def read(self, path: str) -> str | None:
        target = self.root / path
        return target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None


def write_files(root: Path, files: dict[str, str]) -> None:
    """Exact bytes: no newline translation on Windows."""
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
