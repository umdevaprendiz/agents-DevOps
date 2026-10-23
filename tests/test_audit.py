import json
import threading

from devops_agent.audit import AuditLog
from devops_agent.redaction import MASK


def _records(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_audit_log_creates_folder_and_appends_json_lines(tmp_path):
    path = tmp_path / "nested" / "audit.jsonl"
    audit = AuditLog(path)
    audit.log("task", task="investigar ação")
    audit.log("answer", answer="ok")

    records = _records(path)
    assert [r["event"] for r in records] == ["task", "answer"]
    assert records[0]["task"] == "investigar ação"
    assert records[0]["ts"].endswith("+00:00")


def test_audit_log_omits_empty_fields(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.log("task", task="x", subject=None)
    assert "subject" not in _records(tmp_path / "audit.jsonl")[0]


def test_audit_log_redacts_secrets(tmp_path):
    secret = "s3cr3t-" + "value-for-tests"
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.log("tool", output=f"DB_PASSWORD={secret}", args={"api_key": secret})

    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert secret not in text
    assert MASK in text


def test_audit_log_serializes_unknown_types_as_text(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.log("tool", path=tmp_path)
    assert _records(tmp_path / "audit.jsonl")[0]["path"] == str(tmp_path)


def test_audit_log_is_safe_with_parallel_writers(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")

    def write(worker):
        for step in range(50):
            audit.log("tool", worker=worker, step=step, output="x" * 500)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(_records(tmp_path / "audit.jsonl")) == 400
