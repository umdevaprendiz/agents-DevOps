import json

import pytest

from devops_agent import cli, i18n, security
from devops_agent import docker_tools as dk
from devops_agent.config import Config
from devops_agent.security import runtime
from devops_agent.workspace import Workspace
from tests.conftest import write

BAD_DOCKERFILE = "FROM node\nCOPY . /app\n"
BAD_COMPOSE = "services:\n  db:\n    image: postgres:16.3\n    ports: ['5432:5432']\n    mem_limit: 1g\n"
BRUTE_FORCE = "\n".join(f"Failed password for root from 203.0.113.7 port {n}" for n in range(12)) + "\n"


@pytest.fixture
def risky_project(tmp_path):
    write(tmp_path, "Dockerfile", BAD_DOCKERFILE)
    write(tmp_path, "docker-compose.yml", BAD_COMPOSE)
    write(tmp_path, "logs/auth.log", BRUTE_FORCE)
    return Workspace(tmp_path)


def rule_ids(findings) -> list[str]:
    return [finding.rule.id for finding in findings]


# --- Orchestration -----------------------------------------------------------------------------------

def test_audit_combines_every_area_most_severe_first(risky_project):
    findings = security.audit(risky_project, docker=False)
    assert {"DF001", "DF002", "DF005", "DC004", "LG001"} <= set(rule_ids(findings))
    severities = [f.severity for f in findings]
    assert severities == sorted(severities, key=security.SEVERITIES.index)


def test_docker_errors_do_not_break_the_audit(risky_project, monkeypatch):
    def down():
        raise dk.DockerError("daemon not running")

    monkeypatch.setattr(runtime, "running_containers", down)
    assert security.audit(risky_project, docker=True) == security.audit(risky_project, docker=False)


def test_clean_project(tmp_path):
    write(tmp_path, "README.md", "hello\n")
    assert security.audit(Workspace(tmp_path), docker=False) == []


# --- Output -----------------------------------------------------------------------------------------

def test_text_report(risky_project):
    report = security.format_report(security.audit(risky_project, docker=False))
    assert report.startswith("Security audit: ")
    assert "[HIGH] DC004 · docker-compose.yml (service db)" in report
    assert "Fix: " in report


def test_text_report_without_findings():
    assert security.format_report([]) == "Security audit: no findings."


def test_json_report(risky_project):
    report = json.loads(security.as_json(security.audit(risky_project, docker=False)))
    assert report["summary"]["high"] >= 3
    assert {"rule", "severity", "location", "title", "detail", "fix"} == set(report["findings"][0])


@pytest.mark.parametrize("threshold, expected", [("high", True), ("medium", True), ("low", True), ("never", False)])
def test_fails_on_threshold(risky_project, threshold, expected):
    assert security.fails(security.audit(risky_project, docker=False), threshold) is expected


def test_only_low_findings_pass_a_high_threshold(tmp_path):
    write(tmp_path, "Dockerfile", "FROM alpine:3.20\nUSER 1000\n")  # only DF006 (low)
    findings = security.audit(Workspace(tmp_path), docker=False)
    assert rule_ids(findings) == ["DF006"]
    assert security.fails(findings, "high") is False
    assert security.fails(findings, "low") is True


# --- CLI -----------------------------------------------------------------------------------------------

def audit_args(*extra):
    return cli.build_parser().parse_args(["audit", "--no-docker", *extra])


def config_for(path) -> Config:
    cfg = Config()
    cfg.workspace = path
    return cfg


def test_cli_exit_codes(risky_project, tmp_path):
    assert cli.run_audit(config_for(risky_project.root), audit_args("--json")) == 1
    assert cli.run_audit(config_for(risky_project.root), audit_args("--json", "--fail-on", "never")) == 0
    assert cli.run_audit(config_for(tmp_path / "missing"), audit_args()) == 2


def test_cli_json_is_utf8_in_any_language(risky_project, capsysbinary):
    i18n.set_language("pt-BR")
    cli.run_audit(config_for(risky_project.root), audit_args("--json"))
    report = json.loads(capsysbinary.readouterr().out.decode("utf-8"))
    assert any("serviço" in finding["location"] for finding in report["findings"])


def test_audit_does_not_need_ollama(risky_project, monkeypatch):
    monkeypatch.setattr(cli, "load_env_file", lambda: False)
    monkeypatch.setattr(cli, "preflight", lambda cfg: pytest.fail("audit must not run the preflight"))
    monkeypatch.setenv("AGENT_WORKSPACE", str(risky_project.root))
    assert cli.main(["audit", "--no-docker", "--json", "--fail-on", "never"]) == 0
