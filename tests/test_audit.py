import json

from devops_agent.audit import AuditLog


def test_audit_log_creates_folder_and_appends_json_lines(tmp_path):
    path = tmp_path / "nested" / "audit.jsonl"
    audit = AuditLog(path)
    audit.log("task", task="investigar ação")
    audit.log("answer", answer="ok")

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["event"] for r in records] == ["task", "answer"]
    assert records[0]["task"] == "investigar ação"
    assert records[0]["ts"].endswith("+00:00")


def test_audit_log_serializes_unknown_types_as_text(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.log("tool", path=tmp_path)
    assert str(tmp_path).replace("\\", "\\\\") in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
