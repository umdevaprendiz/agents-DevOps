import pytest

from devops_agent.security.compose import check, parse_port
from devops_agent.workspace import Workspace
from tests.conftest import write

FAKE_PASSWORD = "not-a-real-" + "password-42"

COMPOSE = f"""
services:
  db:
    image: postgres
    environment:
      POSTGRES_PASSWORD: {FAKE_PASSWORD}
      POSTGRES_DB: app
    ports: ["5432:5432"]
  cache:
    image: redis:7.2
    ports: ["127.0.0.1:6379:6379"]
    mem_limit: 256m
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
  agent:
    build: .
    privileged: true
    network_mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - API_KEY=${{API_KEY}}
      - LOG_LEVEL=info
"""


@pytest.fixture
def findings(tmp_path):
    write(tmp_path, "docker-compose.yml", COMPOSE)
    return check(Workspace(tmp_path), "docker-compose.yml")


def by_service(findings, service) -> set[str]:
    return {f.rule.id for f in findings if f"(service {service})" in f.location}


def test_database_service_findings(findings):
    assert by_service(findings, "db") == {"DC003", "DC004", "DC005", "DC007", "DC008"}


def test_a_well_configured_service_is_clean(findings):
    assert by_service(findings, "cache") == set()


def test_privileged_agent_findings(findings):
    # build: . means a local image (no pin needed) and ${API_KEY} is a reference, not a secret
    assert by_service(findings, "agent") == {"DC001", "DC002", "DC006", "DC008"}


def test_secret_values_never_appear(findings):
    assert all(FAKE_PASSWORD not in f.detail for f in findings)


def test_exposed_database_names_the_engine(findings):
    (finding,) = [f for f in findings if f.rule.id == "DC004"]
    assert finding.detail == "5432:5432 (PostgreSQL)"


def test_long_port_syntax_and_localhost_binding(tmp_path):
    write(tmp_path, "compose.yaml", """
services:
  mongo:
    image: mongo:7.0
    mem_limit: 1g
    healthcheck: {test: ["CMD", "mongosh", "--eval", "1"]}
    ports:
      - target: 27017
        published: 27017
      - target: 27018
        host_ip: 127.0.0.1
""")
    found = check(Workspace(tmp_path), "compose.yaml")
    assert [f.rule.id for f in found] == ["DC004"]


def test_invalid_yaml_is_skipped(tmp_path):
    write(tmp_path, "docker-compose.yml", "services: [unclosed\n")
    assert check(Workspace(tmp_path), "docker-compose.yml") == []


@pytest.mark.parametrize(
    "entry, expected",
    [
        ("5432", (None, 5432)),
        ("5432:5432", (None, 5432)),
        ("8080:80/tcp", (None, 80)),
        ("127.0.0.1:5432:5432", ("127.0.0.1", 5432)),
        ("[::1]:5432:5432", ("::1", 5432)),
        ("9000-9001:9000-9001", (None, None)),
        (6379, (None, 6379)),
        ({"target": 5432, "host_ip": "0.0.0.0"}, ("0.0.0.0", 5432)),
    ],
)
def test_parse_port(entry, expected):
    assert parse_port(entry) == expected
