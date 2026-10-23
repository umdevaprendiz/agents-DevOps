import pytest

from devops_agent.security import secrets
from devops_agent.security.heuristics import looks_like_secret, plausible_secret
from devops_agent.workspace import Workspace
from tests.conftest import git, write

FAKE_PASSWORD = "hunter" + "2-very-secret"
FAKE_TOKEN = "gh" + "p_" + "A1b2C3d4" * 5


# --- Heuristics -------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, plausible",
    [
        (FAKE_PASSWORD, True),
        ('"' + FAKE_PASSWORD + '"', True),
        ("${DB_PASSWORD}", False),
        ("$DB_PASSWORD", False),
        ("short", False),
        ("has a space inside", False),
        ("/run/secrets/db_password", False),
        ("https://vault.local/v1/db", False),
        ('os.environ["DB_PASSWORD"]', False),
        ("settings.API_KEY", False),
        ("changeme123", False),
        ("<your-api-key>", False),
        ("[REDACTED]", False),
    ],
)
def test_plausible_secret(value, plausible):
    assert plausible_secret(value) is plausible


@pytest.mark.parametrize(
    "line, secret",
    [
        (f"DB_PASSWORD: {FAKE_PASSWORD}", True),
        (f'"api_key": "{FAKE_PASSWORD}"', True),
        (f"client = Client({FAKE_TOKEN!r})", True),
        ('"sec.detail.secrets": "{count} lines, e.g.: {example}",', False),
        ('"workspace.secret": "access denied to a secret file: {path}",', False),
        ('password = os.environ["DB_PASSWORD"]', False),
        ("token = get_token()", False),
        ("DB_PASSWORD=${DB_PASSWORD}", False),
    ],
)
def test_looks_like_secret(line, secret):
    assert looks_like_secret(line) is secret


@pytest.mark.parametrize(
    "path, scanned",
    [
        ("app/config.yml", True),
        ("src/settings.py", True),
        ("Dockerfile.prod", True),
        (".env.example", True),
        ("README.md", False),
        ("tests/test_api.py", False),
        ("src/api.test.js", False),
        ("docs/setup.yml", False),
        ("logo.png", False),
    ],
)
def test_scannable(path, scanned):
    assert secrets.scannable(path) is scanned


# --- Repository checks ------------------------------------------------------------------------------

def test_hardcoded_secret_is_reported_with_line_and_redacted(git_repo):
    write(git_repo, "app/config.yml", f"port: 3000\ndb_password: {FAKE_PASSWORD}\n")
    write(git_repo, "tests/fixtures.yml", f"db_password: {FAKE_PASSWORD}\n")
    (finding,) = [f for f in secrets.check(Workspace(git_repo)) if f.rule.id == "SC001"]
    assert finding.location == "app/config.yml:2"
    assert FAKE_PASSWORD not in finding.detail


def test_committed_secret_file(git_repo):
    write(git_repo, ".env.production", "TOKEN=x\n")
    git(git_repo, "add", "-f", ".env.production")
    git(git_repo, "commit", "-q", "-m", "oops")
    assert [(f.rule.id, f.location) for f in secrets.check(Workspace(git_repo))] == [("SC002", ".env.production")]


def test_secret_file_that_git_would_commit(git_repo):
    write(git_repo, ".env", "TOKEN=x\n")
    assert [(f.rule.id, f.location) for f in secrets.check(Workspace(git_repo))] == [("SC003", ".env")]


def test_ignored_secret_file_is_fine(git_repo):
    write(git_repo, ".gitignore", ".env\n")
    write(git_repo, ".env", "TOKEN=x\n")
    assert secrets.check(Workspace(git_repo)) == []


def test_secret_files_are_only_listed_never_read(git_repo, monkeypatch):
    write(git_repo, ".env", f"TOKEN={FAKE_TOKEN}\n")
    findings = secrets.check(Workspace(git_repo))
    assert all(FAKE_TOKEN not in f.detail for f in findings)
