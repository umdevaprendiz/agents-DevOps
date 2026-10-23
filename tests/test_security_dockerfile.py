import pytest

from devops_agent.security.dockerfile import base_image, check, is_unpinned, parse
from devops_agent.workspace import Workspace
from tests.conftest import write

FAKE_SECRET = "s3cr3t-" + "value-for-tests"

BAD = (
    "FROM node\n"
    "ENV API_TOKEN=" + FAKE_SECRET + " LOG_LEVEL=info\n"
    "RUN curl -fsSL https://example.com/install.sh | sh\n"
    "RUN apt-get update && apt-get install -y git\n"
    "RUN chmod -R 777 /app\n"
    "COPY . /app\n"
    'CMD ["node", "server.js"]\n'
)
GOOD = (
    "FROM python:3.12-slim AS build\n"
    "RUN pip wheel --wheel-dir /wheels .\n"
    "FROM python:3.12-slim\n"
    "COPY --from=build /wheels /wheels\n"
    "ENV DB_PASSWORD=${DB_PASSWORD} SECRET_FILE=/run/secrets/db\n"
    "RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*\n"
    "RUN useradd -r app\n"
    "USER app\n"
    "HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1\n"
)


def rules(findings) -> set[str]:
    return {finding.rule.id for finding in findings}


def project(tmp_path, dockerfile: str, dockerignore: bool = False) -> Workspace:
    write(tmp_path, "Dockerfile", dockerfile)
    if dockerignore:
        write(tmp_path, ".dockerignore", ".env\n.git\n")
    return Workspace(tmp_path)


# --- Parsing ----------------------------------------------------------------------------------------

def test_parse_joins_continuations_and_skips_comments():
    text = "# syntax\nFROM alpine:3.20\nRUN apk add \\\n    # a comment inside\n    curl\n"
    parsed = parse(text)
    assert [(i.line, i.keyword) for i in parsed] == [(2, "FROM"), (3, "RUN")]
    assert parsed[1].args == "apk add curl"


def test_base_image_reads_platform_and_alias():
    assert base_image("--platform=linux/amd64 golang:1.22 AS build") == ("golang:1.22", "build")
    assert base_image("alpine:3.20") == ("alpine:3.20", None)


@pytest.mark.parametrize(
    "image, unpinned",
    [
        ("node", True),
        ("node:latest", True),
        ("registry.local:5000/team/app", True),
        ("node:20.11-alpine", False),
        ("registry.local:5000/team/app:1.4.2", False),
        ("node@sha256:" + "a" * 64, False),
        ("scratch", False),
        ("${BASE_IMAGE}", False),
    ],
)
def test_is_unpinned(image, unpinned):
    assert is_unpinned(image) is unpinned


def test_build_stage_names_are_not_images():
    assert is_unpinned("build", {"build"}) is False


# --- Rules ------------------------------------------------------------------------------------------

def test_every_rule_fires_on_a_bad_dockerfile(tmp_path):
    findings = check(project(tmp_path, BAD), "Dockerfile")
    assert rules(findings) == {"DF001", "DF002", "DF003", "DF004", "DF005", "DF006", "DF007", "DF008"}


def test_a_hardened_dockerfile_is_clean(tmp_path):
    assert check(project(tmp_path, GOOD, dockerignore=True), "Dockerfile") == []


def test_findings_point_to_the_line(tmp_path):
    findings = {f.rule.id: f for f in check(project(tmp_path, BAD), "Dockerfile")}
    assert findings["DF003"].location == "Dockerfile:3"
    assert findings["DF005"].location == "Dockerfile:6"


def test_secret_evidence_is_redacted(tmp_path):
    (finding,) = [f for f in check(project(tmp_path, BAD), "Dockerfile") if f.rule.id == "DF004"]
    assert FAKE_SECRET not in finding.detail
    assert "[REDACTED]" in finding.detail


def test_legacy_env_form_is_checked(tmp_path):
    dockerfile = "FROM alpine:3.20\nENV API_TOKEN " + FAKE_SECRET + "\nUSER 1000\nHEALTHCHECK NONE\n"
    assert "DF004" in rules(check(project(tmp_path, dockerfile, dockerignore=True), "Dockerfile"))


@pytest.mark.parametrize("user, flagged", [("root", True), ("0:0", True), ("1000", False), ("app", False)])
def test_explicit_user(tmp_path, user, flagged):
    dockerfile = f"FROM alpine:3.20\nUSER {user}\nHEALTHCHECK CMD true\n"
    assert ("DF002" in rules(check(project(tmp_path, dockerfile), "Dockerfile"))) is flagged


def test_user_only_in_the_build_stage_still_runs_as_root(tmp_path):
    dockerfile = "FROM golang:1.22 AS build\nUSER builder\nFROM alpine:3.20\nCOPY --from=build /app /app\n"
    assert "DF002" in rules(check(project(tmp_path, dockerfile), "Dockerfile"))


def test_unreadable_dockerfile_is_skipped(tmp_path):
    assert check(Workspace(tmp_path), "Dockerfile") == []
