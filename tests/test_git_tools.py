import pytest

from devops_agent import git_tools as gt
from tests.conftest import COMPOSE, git, write

NEW_COMPOSE = COMPOSE.replace("8081", "80")


def test_is_repo(git_repo, tmp_path):
    assert gt.is_repo(git_repo)
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not gt.is_repo(plain)


def test_commit_files_never_touches_working_tree_or_index(git_repo):
    head = gt.head_commit(git_repo)
    commit = gt.commit_files(git_repo, head, {"docker-compose.yml": NEW_COMPOSE}, "Fix healthcheck port\n\nWhy.")

    assert git(git_repo, "status", "--porcelain") == ""
    assert (git_repo / "docker-compose.yml").read_text(encoding="utf-8") == COMPOSE
    assert gt.head_commit(git_repo) == head
    assert gt.read_blob(git_repo, commit, "docker-compose.yml") == NEW_COMPOSE
    assert gt.message_of(git_repo, commit) == "Fix healthcheck port\n\nWhy."


def test_agent_commits_use_the_agent_identity(git_repo):
    commit = gt.commit_files(git_repo, gt.head_commit(git_repo), {"a.txt": "x\n"}, "msg")
    assert git(git_repo, "log", "-1", "--format=%an <%ae>", commit) == f"{gt.AGENT_NAME} <{gt.AGENT_EMAIL}>"


def test_commit_files_can_create_files_in_new_folders(git_repo):
    commit = gt.commit_files(git_repo, gt.head_commit(git_repo), {"ops/new/file.txt": "hello\n"}, "msg")
    assert gt.read_blob(git_repo, commit, "ops/new/file.txt") == "hello\n"


def test_commit_files_keeps_the_executable_bit(git_repo):
    write(git_repo, "deploy.sh", "echo old\n")
    git(git_repo, "add", "deploy.sh")
    git(git_repo, "update-index", "--chmod=+x", "deploy.sh")
    git(git_repo, "commit", "-q", "-m", "script")
    commit = gt.commit_files(git_repo, gt.head_commit(git_repo), {"deploy.sh": "echo new\n"}, "msg")
    assert gt.file_mode(git_repo, commit, "deploy.sh") == "100755"


def test_commit_files_keeps_crlf_bytes(git_repo):
    commit = gt.commit_files(git_repo, gt.head_commit(git_repo), {"win.txt": "a\r\nb\r\n"}, "msg")
    assert gt.read_blob(git_repo, commit, "win.txt") == "a\r\nb\r\n"


def test_read_blob_returns_none_for_missing_files(git_repo):
    assert gt.read_blob(git_repo, "HEAD", "missing.txt") is None


def test_branches_are_listed_newest_first_and_filtered(git_repo):
    head = gt.head_commit(git_repo)
    first = gt.commit_files(git_repo, head, {"a.txt": "1\n"}, "first")
    gt.create_branch(git_repo, "agent/first", first)
    git(git_repo, "branch", "other", head)
    # commit-tree timestamps have one-second resolution; force a later committer date
    second = gt._git(git_repo, ["commit-tree", f"{first}^{{tree}}", "-p", head, "-m", "second"],
                     env={**gt.AGENT_IDENTITY, "GIT_COMMITTER_DATE": "2090-01-01 00:00:00 +0000"}).strip()
    gt.create_branch(git_repo, "agent/second", second)
    assert gt.branches(git_repo, "agent/") == ["agent/second", "agent/first"]


def test_merge_and_revert(git_repo):
    commit = gt.commit_files(git_repo, gt.head_commit(git_repo), {"docker-compose.yml": NEW_COMPOSE}, "fix")
    gt.create_branch(git_repo, "agent/fix", commit)

    gt.merge(git_repo, "agent/fix", "devops-agent: apply agent/fix")
    assert (git_repo / "docker-compose.yml").read_text(encoding="utf-8") == NEW_COMPOSE
    assert gt.is_ancestor(git_repo, commit)

    merge = gt.last_merge(git_repo, "devops-agent: apply")
    assert merge and not gt.is_reverted(git_repo, merge)
    gt.revert_merge(git_repo, merge)
    assert (git_repo / "docker-compose.yml").read_text(encoding="utf-8") == COMPOSE
    assert gt.is_reverted(git_repo, merge)


def test_conflicting_merge_is_aborted(git_repo):
    commit = gt.commit_files(git_repo, gt.head_commit(git_repo), {"docker-compose.yml": NEW_COMPOSE}, "fix")
    gt.create_branch(git_repo, "agent/fix", commit)
    write(git_repo, "docker-compose.yml", COMPOSE.replace("8081", "9999"))
    git(git_repo, "commit", "-q", "-am", "operator changed the same line")

    with pytest.raises(gt.GitError):
        gt.merge(git_repo, "agent/fix", "msg")
    assert not (git_repo / ".git" / "MERGE_HEAD").exists()
    assert git(git_repo, "status", "--porcelain") == ""


def test_errors_are_wrapped(git_repo):
    with pytest.raises(gt.GitError):
        gt.commit_of(git_repo, "does-not-exist")


def test_has_remote(git_repo):
    assert not gt.has_remote(git_repo)
