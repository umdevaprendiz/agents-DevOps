import pytest

from devops_agent import workspace as workspace_module
from devops_agent.workspace import Workspace, WorkspaceError, is_secret
from tests.conftest import git, write

FAKE_PASSWORD = "not-a-real-" + "password"


@pytest.fixture
def folder(tmp_path) -> Workspace:
    """A plain folder (not a git repository) with code, a secret file, a key, vendored folders and a binary."""
    root = tmp_path / "plain"
    write(root, "docker-compose.yml", "services:\n  web:\n    image: nginx\n")
    write(root, "src/app.py", "print('hello')\nraise ValueError('boom')\n")
    write(root, ".env", f"DB_PASSWORD={FAKE_PASSWORD}\n")
    write(root, "keys/server.pem", "-----BEGIN" + " PRIVATE KEY-----\nabc\n")
    write(root, "node_modules/lib/index.js", "module.exports = 1\n")
    write(root, ".venv/lib/site.py", "x = 1\n")
    (root / "logo.png").write_bytes(b"\x89PNG\0\0data")
    return Workspace(root)


# --- Paths ------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name, secret",
    [
        (".env", True),
        (".env.production", True),
        (".env.example", False),
        ("id_rsa", True),
        ("id_rsa.pub", False),
        ("server.pem", True),
        ("tls.key", True),
        ("docker-compose.yml", False),
    ],
)
def test_is_secret(name, secret):
    assert is_secret(name) is secret


def test_resolve_accepts_paths_inside_the_workspace(folder):
    assert folder.resolve("src/app.py") == folder.root / "src" / "app.py"


@pytest.mark.parametrize("path", ["../outside.txt", "src/../../outside.txt"])
def test_resolve_refuses_escapes(folder, path):
    with pytest.raises(WorkspaceError, match="outside"):
        folder.resolve(path)


def test_resolve_refuses_absolute_paths_outside(folder, tmp_path):
    with pytest.raises(WorkspaceError, match="outside"):
        folder.resolve(str(tmp_path / "elsewhere.txt"))


@pytest.mark.parametrize("path", [".env", "keys/server.pem", ".git/config"])
def test_resolve_refuses_secret_files(folder, path):
    with pytest.raises(WorkspaceError, match="secret"):
        folder.resolve(path)


# --- list_files -------------------------------------------------------------------------------------

def test_list_files_hides_secrets_and_vendored_folders(folder):
    assert folder.list_files().splitlines() == ["docker-compose.yml", "logo.png", "src/app.py"]


def test_list_files_filters_by_path_or_name(folder):
    assert folder.list_files("*.py") == "src/app.py"
    assert folder.list_files("src/*") == "src/app.py"
    assert folder.list_files("docker-compose.yml") == "docker-compose.yml"


def test_globs_are_case_sensitive_on_every_os(tmp_path):
    write(tmp_path, "Dockerfile", "FROM alpine:3.20\n")
    write(tmp_path, "src/dockerfile.py", "x = 1\n")
    assert Workspace(tmp_path).list_files("Dockerfile*") == "Dockerfile"


def test_list_files_reports_when_nothing_matches(folder):
    assert folder.list_files("*.tf") == "(no files)"


def test_list_files_respects_gitignore_in_a_repository(git_repo):
    write(git_repo, ".gitignore", "ignored.txt\n")
    write(git_repo, "ignored.txt", "x")
    write(git_repo, "new.txt", "x")
    names = Workspace(git_repo).list_files().splitlines()
    assert "new.txt" in names and "ignored.txt" not in names and "docker-compose.yml" in names


# --- read_file --------------------------------------------------------------------------------------

def test_read_file_numbers_lines_and_shows_a_header(folder):
    text = folder.read_file("docker-compose.yml")
    assert text.splitlines() == [
        "docker-compose.yml (lines 1-3 of 3)",
        "1| services:",
        "2|   web:",
        "3|     image: nginx",
    ]


def test_read_file_reads_a_window(folder):
    assert folder.read_file("src/app.py", start_line=2, max_lines=1).splitlines()[1:] == ["2| raise ValueError('boom')"]


def test_read_file_refuses_missing_binary_and_secret_files(folder):
    with pytest.raises(WorkspaceError, match="not found"):
        folder.read_file("missing.txt")
    with pytest.raises(WorkspaceError, match="binary"):
        folder.read_file("logo.png")
    with pytest.raises(WorkspaceError, match="secret"):
        folder.read_file(".env")


def test_read_file_refuses_huge_files(folder, monkeypatch):
    monkeypatch.setattr(workspace_module, "MAX_FILE_BYTES", 10)
    with pytest.raises(WorkspaceError, match="too big"):
        folder.read_file("src/app.py")


# --- search -----------------------------------------------------------------------------------------

def test_search_uses_regular_expressions(folder):
    assert folder.search(r"raise \w+Error") == "src/app.py:2: raise ValueError('boom')"


def test_search_falls_back_to_plain_text_for_invalid_regex(folder):
    assert folder.search("print(") == "src/app.py:1: print('hello')"


def test_search_can_be_limited_by_glob(folder):
    assert folder.search("e", glob="*.yml").startswith("docker-compose.yml:")


def test_search_never_looks_inside_secret_files(folder):
    assert folder.search(FAKE_PASSWORD) == "(no matches)"


# --- git ----------------------------------------------------------------------------------------------

def test_git_diff_never_includes_secret_files(git_repo):
    write(git_repo, ".env.production", "TOKEN=old\n")
    git(git_repo, "add", "-f", ".env.production")
    git(git_repo, "commit", "-q", "-m", "tracked secret (bad practice)")
    write(git_repo, ".env.production", f"TOKEN={FAKE_PASSWORD}\n")
    write(git_repo, "app/config.yml", "port: 8080\nlog_level: info\n")

    diff = Workspace(git_repo).git_diff()
    assert "port: 8080" in diff
    assert FAKE_PASSWORD not in diff
    with pytest.raises(WorkspaceError):
        Workspace(git_repo).git_diff(".env.production")


def test_git_diff_reports_a_clean_tree(git_repo):
    assert Workspace(git_repo).git_diff() == "(no uncommitted changes)"


def test_git_status_and_log(git_repo):
    workspace = Workspace(git_repo)
    assert workspace.git_status().startswith("## main")
    assert "initial" in workspace.git_log()
