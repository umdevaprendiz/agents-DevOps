import io
import json
from types import SimpleNamespace

import pytest
from rich.console import Console

from devops_agent import proposals as proposals_module
from devops_agent.agent import Agent
from devops_agent.audit import AuditLog
from devops_agent.config import Config
from devops_agent.proposals import Edit, ProposalError, ProposalStore, apply_edit, parse_edits
from devops_agent.redaction import MASK
from devops_agent.tools import build_toolbox
from devops_agent.workspace import Workspace, WorkspaceError
from tests.conftest import COMPOSE, FakeClient, assistant, git, write

PORT_EDIT = {"path": "docker-compose.yml", "old_text": "localhost:8081", "new_text": "localhost:80"}
FAKE_SECRET = "s3cr3t-" + "value-for-tests"


@pytest.fixture
def store(git_repo) -> ProposalStore:
    return ProposalStore(Workspace(git_repo))


def compose(repo) -> str:
    return (repo / "docker-compose.yml").read_text(encoding="utf-8")


# --- Parsing edits ---------------------------------------------------------------------------------

def test_parse_edits_accepts_list_dict_and_json_string():
    expected = [Edit("a", "x", "y")]
    item = {"path": "a", "old_text": "x", "new_text": "y"}
    assert parse_edits([item]) == expected
    assert parse_edits(item) == expected
    assert parse_edits(json.dumps([item])) == expected


@pytest.mark.parametrize("raw", ["not json", [], None, [{"old_text": "x"}], ["text"]])
def test_parse_edits_rejects_invalid_input(raw):
    with pytest.raises(ProposalError):
        parse_edits(raw)


# --- Applying one edit -----------------------------------------------------------------------------

def test_apply_edit_replaces_the_unique_text():
    assert apply_edit("a\nb\nc\n", Edit("f", "b\n", "B\n")) == "a\nB\nc\n"


def test_apply_edit_refuses_ambiguous_or_missing_text():
    with pytest.raises(ProposalError, match="2 times"):
        apply_edit("x\nx\n", Edit("f", "x", "y"))
    with pytest.raises(ProposalError, match="not found"):
        apply_edit("abc", Edit("f", "zzz", "y"))


def test_apply_edit_creates_new_files_only():
    assert apply_edit(None, Edit("f", "", "new\n")) == "new\n"
    with pytest.raises(ProposalError, match="already exists"):
        apply_edit("old", Edit("f", "", "new"))
    with pytest.raises(ProposalError, match="does not exist"):
        apply_edit(None, Edit("f", "x", "y"))


def test_apply_edit_matches_crlf_files():
    assert apply_edit("a\r\nb\r\n", Edit("f", "a\nb\n", "a\nc\n")) == "a\r\nc\r\n"


def test_apply_edit_ignores_copied_line_numbers():
    content = "port: 3000\nlog_level: info\n"
    edit = Edit("f", "1| port: 3000\n2| log_level: info", "1| port: 3000\n2| log_level: debug")
    assert apply_edit(content, edit) == "port: 3000\nlog_level: debug\n"


def test_apply_edit_never_touches_redacted_lines():
    with pytest.raises(ProposalError, match=r"\[REDACTED\]"):
        apply_edit(f"password: {MASK}\n", Edit("f", f"password: {MASK}", "password: x"))


def test_apply_edit_never_writes_secrets():
    with pytest.raises(ProposalError, match="secret"):
        apply_edit("a\n", Edit("f", "a", f"DB_PASSWORD={FAKE_SECRET}"))


def test_apply_edit_allows_variable_references():
    assert apply_edit("a\n", Edit("f", "a", "DB_PASSWORD=${DB_PASSWORD}")) == "DB_PASSWORD=${DB_PASSWORD}\n"


# --- Creating proposals -----------------------------------------------------------------------------

def test_create_puts_the_change_on_its_own_branch(store, git_repo):
    proposal = store.create("Fix healthcheck port", "nginx listens on 80", [PORT_EDIT])

    assert proposal.branch.startswith("agent/fix-healthcheck-port-")
    assert proposal.title == "Fix healthcheck port"
    assert compose(git_repo) == COMPOSE  # the operator's files are untouched
    assert git(git_repo, "status", "--porcelain") == ""
    diff = store.diff(proposal)
    assert "-      test: [\"CMD\", \"wget\", \"-q\", \"http://localhost:8081/\"]" in diff
    assert "+      test: [\"CMD\", \"wget\", \"-q\", \"http://localhost:80/\"]" in diff


def test_create_applies_several_edits_to_the_same_file(store):
    edits = [PORT_EDIT, {"path": "docker-compose.yml", "old_text": "nginx:alpine", "new_text": "nginx:1.27-alpine"}]
    diff = store.diff(store.create("Pin and fix", "why", edits))
    assert "localhost:80/" in diff and "nginx:1.27-alpine" in diff


def test_create_can_add_a_new_file(store):
    proposal = store.create("Add ignore", "why", [{"path": ".dockerignore", "old_text": "", "new_text": ".env\n"}])
    assert "+.env" in store.diff(proposal)


@pytest.mark.parametrize("path", ["../outside.yml", ".env", ".git/config"])
def test_create_refuses_paths_outside_or_secret(store, path):
    with pytest.raises(WorkspaceError):
        store.create("x", "y", [{"path": path, "old_text": "", "new_text": "z"}])


def test_failed_edit_creates_nothing(store, git_repo):
    with pytest.raises(ProposalError):
        store.create("x", "y", [{"path": "docker-compose.yml", "old_text": "missing", "new_text": "z"}])
    assert store.pending() == []


def test_store_needs_a_git_repository(tmp_path):
    with pytest.raises(ProposalError, match="not a git repository"):
        ProposalStore(Workspace(tmp_path)).create("x", "y", [PORT_EDIT])


def test_store_works_from_a_subfolder_workspace(git_repo):
    store = ProposalStore(Workspace(git_repo / "app"))
    proposal = store.create("Debug logs", "why", [{"path": "config.yml", "old_text": "info", "new_text": "debug"}])
    assert "+log_level: debug" in store.diff(proposal)


# --- Finding proposals ------------------------------------------------------------------------------

def test_get_finds_the_latest_by_default_or_by_id(store):
    first = store.create("First", "why", [PORT_EDIT])
    assert store.get() == first
    assert store.get(first.id) == first
    assert store.get(first.branch) == first
    with pytest.raises(ProposalError, match="matches"):
        store.get("nope")


def test_get_without_proposals(store):
    with pytest.raises(ProposalError, match="No pending proposals"):
        store.get()


# --- Decisions ---------------------------------------------------------------------------------------

def test_apply_merges_into_the_current_branch(store, git_repo):
    proposal = store.create("Fix port", "why", [PORT_EDIT])
    store.apply(proposal)

    assert "localhost:80/" in compose(git_repo)
    assert store.pending() == []
    assert proposal.branch not in git(git_repo, "branch")
    assert git(git_repo, "log", "-1", "--format=%s").startswith("devops-agent: apply")


def test_undo_reverts_the_last_applied_proposal_once(store, git_repo):
    store.apply(store.create("Fix port", "why", [PORT_EDIT]))
    store.undo_last()
    assert compose(git_repo) == COMPOSE
    with pytest.raises(ProposalError, match="already"):
        store.undo_last()


def test_undo_without_applied_proposals(store):
    with pytest.raises(ProposalError, match="No applied proposal"):
        store.undo_last()


def test_discard_deletes_the_branch(store, git_repo):
    proposal = store.create("Fix port", "why", [PORT_EDIT])
    store.discard(proposal)
    assert store.pending() == []
    assert compose(git_repo) == COMPOSE


def test_proposals_merged_elsewhere_are_not_pending(store, git_repo):
    proposal = store.create("Fix port", "why", [PORT_EDIT])
    git(git_repo, "merge", "-q", "--no-ff", "-m", "merged by hand", proposal.branch)
    assert store.pending() == []


def test_pull_request_needs_a_remote(store):
    with pytest.raises(ProposalError, match="origin"):
        store.open_pull_request(store.create("Fix port", "why", [PORT_EDIT]))


def test_pull_request_pushes_the_branch(store, git_repo, tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(git_repo, "remote", "add", "origin", str(remote))
    monkeypatch.setattr(proposals_module.shutil, "which", lambda name: None)  # no GitHub CLI

    proposal = store.create("Fix port", "why", [PORT_EDIT])
    message = store.open_pull_request(proposal)

    assert proposal.branch in message and "gh" in message
    assert proposal.branch in git(remote, "branch")


# --- End to end: the model proposes, the operator applies --------------------------------------------

def test_agent_proposes_a_change_that_the_operator_applies(store, git_repo, tmp_path):
    workspace = store.workspace
    cfg = Config()
    agent = Agent(
        cfg, Console(file=io.StringIO()), lambda tool, args: False, AuditLog(tmp_path / "audit.jsonl"),
        tools=build_toolbox(workspace, store),
    )
    agent.client = FakeClient(
        assistant(calls=[("read_file", {"path": "docker-compose.yml"})]),
        assistant(calls=[("propose_change", {"title": "Fix healthcheck port", "explanation": "nginx uses 80",
                                             "edits": [PORT_EDIT]})]),
        assistant("Proposed a fix for the healthcheck port."),
    )

    answer = agent.run("the healthcheck of web is failing")

    tool_outputs = [m["content"] for m in agent.client.calls[2]["messages"] if isinstance(m, dict) and m["role"] == "tool"]
    assert "1| services:" in tool_outputs[0]
    assert "/apply" in tool_outputs[1]
    assert answer == "Proposed a fix for the healthcheck port."
    store.apply(store.get())
    assert "localhost:80/" in compose(git_repo)
