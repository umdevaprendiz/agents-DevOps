from devops_agent import docker_tools as dk
from devops_agent.security import logs
from devops_agent.workspace import Workspace
from tests.conftest import write

FAKE_TOKEN = "gh" + "p_" + "A1b2C3d4" * 5


def failures(count: int, ip: str = "203.0.113.7") -> list[str]:
    return [f"sshd: Failed password for root from {ip} port 22" for _ in range(count)]


def rules(findings) -> list[str]:
    return [finding.rule.id for finding in findings]


def test_brute_force_needs_the_threshold():
    assert logs.check("auth.log", failures(logs.BRUTE_FORCE_THRESHOLD - 1)) == []
    (finding,) = logs.check("auth.log", failures(logs.BRUTE_FORCE_THRESHOLD))
    assert finding.rule.id == "LG001"


def test_brute_force_names_the_top_sources():
    lines = failures(12, "203.0.113.7") + failures(3, "198.51.100.2")
    (finding,) = logs.check("auth.log", lines)
    assert finding.detail == "15 authentication failures; top sources: 203.0.113.7 (12), 198.51.100.2 (3)"


def test_attack_probes_are_reported_with_an_example():
    lines = ["GET /health 200", 'GET /../../etc/passwd HTTP/1.1" 400', "GET /?q=1' OR '1'='1 403"]
    (finding,) = logs.check("access.log", lines)
    assert finding.rule.id == "LG002"
    assert finding.detail.startswith("2 suspicious requests")


def test_secrets_printed_in_logs_are_reported_redacted():
    (finding,) = logs.check("app.log", [f"connecting with token={FAKE_TOKEN}"])
    assert finding.rule.id == "LG003"
    assert FAKE_TOKEN not in finding.detail


def test_normal_logs_are_clean():
    lines = ["INFO started on port 3000", "GET /health 200", "loaded secret_store config", "token refresh scheduled"]
    assert logs.check("app.log", lines) == []


def test_file_sources_read_project_logs(tmp_path):
    write(tmp_path, "logs/auth.log", "\n".join(failures(10)) + "\n")
    sources = logs.file_sources(Workspace(tmp_path))
    assert [(source, len(lines)) for source, lines in sources] == [("logs/auth.log", 10)]


def test_container_sources_skip_containers_without_logs(monkeypatch):
    monkeypatch.setattr(dk, "list_containers", lambda include_stopped=True: [{"name": "api"}, {"name": "gone"}])

    def container_logs(name, tail):
        if name == "gone":
            raise dk.DockerError("No such container")
        return "line 1\nline 2"

    monkeypatch.setattr(dk, "container_logs", container_logs)
    assert logs.container_sources() == [("container api", ["line 1", "line 2"])]
