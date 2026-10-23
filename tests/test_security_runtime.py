from devops_agent import docker_tools as dk
from devops_agent.security import runtime

RISKY = {
    "name": "db",
    "privileged": True,
    "mounts": ["/var/run/docker.sock:/var/run/docker.sock", "/data:/var/lib/postgresql/data"],
    "ports": {"5432/tcp": ["0.0.0.0:5432"], "8080/tcp": ["0.0.0.0:8080"]},
    "user": "",
    "network_mode": "host",
    "memory_limit_mb": None,
}
SAFE = {
    "name": "api",
    "privileged": False,
    "mounts": ["/srv/api:/data"],
    "ports": {"5432/tcp": ["127.0.0.1:5432"]},
    "user": "1000",
    "network_mode": "bridge",
    "memory_limit_mb": 512,
}


def test_every_runtime_rule_fires_on_a_risky_container():
    findings = runtime.check([RISKY])
    assert {f.rule.id for f in findings} == {"RC001", "RC002", "RC003", "RC004", "RC005", "RC006"}
    assert all(f.location == "container db" for f in findings)


def test_a_hardened_container_is_clean():
    assert runtime.check([SAFE]) == []


def test_exposed_database_detail():
    (finding,) = [f for f in runtime.check([RISKY]) if f.rule.id == "RC003"]
    assert finding.detail == "0.0.0.0:5432 -> 5432/tcp (PostgreSQL)"


def test_ipv6_wildcard_counts_as_exposed():
    info = {**SAFE, "ports": {"6379/tcp": [":::6379"]}}
    assert [f.rule.id for f in runtime.check([info])] == ["RC003"]


def test_root_user_written_explicitly():
    assert [f.rule.id for f in runtime.check([{**SAFE, "user": "0:0"}])] == ["RC004"]


def test_running_containers_only_inspects_running_ones(monkeypatch):
    seen = {}

    def list_containers(include_stopped=True):
        seen["include_stopped"] = include_stopped
        return [{"name": "api"}]

    monkeypatch.setattr(dk, "list_containers", list_containers)
    monkeypatch.setattr(dk, "inspect_containers", lambda names: [SAFE] if names == ["api"] else [])
    assert runtime.running_containers() == [SAFE]
    assert seen["include_stopped"] is False
