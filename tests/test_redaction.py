"""Redaction tests. Every fake secret is built at runtime (string concatenation),
so secret scanners such as gitleaks never find a real-looking token in this file."""
import pytest

from devops_agent.redaction import MASK, has_known_token, redact, redact_data

AWS_KEY_ID = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB_TOKEN = "ghp_" + "a1B2" * 9
GITHUB_PAT = "github_pat_" + "A1" * 11
GITLAB_TOKEN = "glpat-" + "x1" * 10
SLACK_TOKEN = "xoxb-" + "1234567890-abcdef"
OPENAI_KEY = "sk-" + "proj" + "X9" * 10
GOOGLE_KEY = "AIza" + "B" * 35
TELEGRAM_TOKEN = "123456789" + ":" + "C" * 35
JWT = "eyJ" + "hbGciOiJIUzI1" + "." + "eyJ" + "zdWIiOiIxMjM0" + "." + "sig" + "nature12345"
PASSWORD = "hunter" + "2-very-secret"
PEM = "-----BEGIN" + " RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END" + " RSA PRIVATE KEY-----"


@pytest.mark.parametrize(
    "text, secret",
    [
        (f"using key {AWS_KEY_ID} for s3", AWS_KEY_ID),
        (f"git clone https://{GITHUB_TOKEN}@github.com/org/repo", GITHUB_TOKEN),
        (f"GITHUB_TOKEN set to {GITHUB_PAT}", GITHUB_PAT),
        (f"registry login {GITLAB_TOKEN}", GITLAB_TOKEN),
        (f"posting with {SLACK_TOKEN}", SLACK_TOKEN),
        (f"client created with {OPENAI_KEY}", OPENAI_KEY),
        (f"maps key {GOOGLE_KEY}", GOOGLE_KEY),
        (f"bot {TELEGRAM_TOKEN} started", TELEGRAM_TOKEN),
        (f"session={JWT}", JWT),
        (f"Authorization: Bearer {OPENAI_KEY}", OPENAI_KEY),
        (f"DB_PASSWORD={PASSWORD}", PASSWORD),
        (f"api_key: '{PASSWORD}'", PASSWORD),
        (f"client_secret = {PASSWORD}", PASSWORD),
        (f"loaded key:\n{PEM}\ndone", "MIIEow"),
    ],
)
def test_known_secret_formats_are_hidden(text, secret):
    result = redact(text)
    assert secret not in result
    assert MASK in result


def test_url_credentials_keep_user_and_host():
    assert redact(f"postgres://app:{PASSWORD}@db:5432/main") == f"postgres://app:{MASK}@db:5432/main"


def test_quoted_values_are_hidden_entirely_and_keep_their_quotes():
    assert redact(f'{{"password": "{PASSWORD} with spaces"}}') == f'{{"password": "{MASK}"}}'


def test_cut_private_key_is_still_hidden():
    cut = PEM.split("-----END")[0]
    assert "MIIEow" not in redact(cut)


@pytest.mark.parametrize(
    "line",
    [
        "Starting API on port 3000...",
        "GET /health 200 OK",
        "PATH=/usr/bin:/bin",
        "https://example.com/docs?page=2",
        "ERROR: could not connect to database at postgres:5432 (connection refused)",
        "User-Agent: curl/8.5.0",
        "panic: missing required environment variable QUEUE_URL",
    ],
)
def test_normal_lines_are_untouched(line):
    assert redact(line) == line


@pytest.mark.parametrize(
    "line",
    [
        "DB_PASSWORD=${DB_PASSWORD}",
        "password: $DB_PASSWORD",
        '"api_key": "${API_KEY}"',
        "postgres://app:${DB_PASS}@db:5432/main",
    ],
)
def test_variable_references_are_not_secrets(line):
    assert redact(line) == line


def test_known_tokens_are_told_apart_from_generic_assignments():
    assert has_known_token(f"using {GITHUB_TOKEN}")
    assert has_known_token(f"postgres://app:{PASSWORD}@db/main")
    assert not has_known_token(f"DB_PASSWORD={PASSWORD}")  # generic assignment: masked, but not a known format


def test_redaction_is_idempotent():
    text = f"DB_PASSWORD={PASSWORD} token={GITHUB_TOKEN} postgres://u:{PASSWORD}@h/db"
    assert redact(redact(text)) == redact(text)


def test_redact_data_walks_nested_structures():
    data = {
        "DB_PASSWORD": "plain-value",
        "nested": [{"token": "another"}, f"Bearer {OPENAI_KEY}"],
        "count": 3,
        "secret": None,
    }
    assert redact_data(data) == {
        "DB_PASSWORD": MASK,
        "nested": [{"token": MASK}, f"Bearer {MASK}"],
        "count": 3,
        "secret": None,
    }
