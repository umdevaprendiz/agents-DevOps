import io
import json
from contextlib import contextmanager
from types import SimpleNamespace

import ollama
import pytest
from rich.console import Console

from devops_agent import agent as agent_module
from devops_agent import i18n
from devops_agent.agent import Agent, _clean, _text_tool_calls, _truncate
from devops_agent.audit import AuditLog
from devops_agent.config import Config
from devops_agent.i18n import t
from devops_agent.redaction import MASK
from devops_agent.tools import Tool
from tests.conftest import FakeClient, assistant

CONTAINER = {"container": {"type": "string"}}
FAKE_TOKEN = "gh" + "p_" + "A1b2C3d4" * 5  # GitHub-like token built at runtime


def _explode(container):
    raise RuntimeError("docker is down")


@pytest.fixture
def fake_tools(monkeypatch):
    """Fake tools: the agent is tested without touching Docker."""
    executed = []

    def read(container):
        executed.append(("read_thing", container))
        return f"data from {container}"

    def change(container):
        executed.append(("change_thing", container))
        return f"{container} changed"

    def leak(container):
        return f"login ok, token={FAKE_TOKEN}"

    tools = {
        "read_thing": Tool("read_thing", "Reads.", CONTAINER, ("container",), read),
        "change_thing": Tool("change_thing", "Changes.", CONTAINER, ("container",), change, needs_approval=True),
        "explode": Tool("explode", "Fails.", CONTAINER, ("container",), _explode),
        "leak": Tool("leak", "Prints a secret.", CONTAINER, ("container",), leak),
    }
    monkeypatch.setattr(agent_module, "TOOLS_BY_NAME", tools)
    return executed


@pytest.fixture
def make_agent(tmp_path, fake_tools):
    """Builds an Agent with a scripted client. Returns agent, client, approvals, executed, output and audit_path."""

    def factory(*replies, approve=True, max_steps=5, label=None, progress=None):
        cfg = Config()
        cfg.max_steps = max_steps
        cfg.audit_file = tmp_path / "audit.jsonl"
        approvals = []

        def approver(tool, args):
            approvals.append((tool.name, args))
            return approve

        output = io.StringIO()
        console = Console(file=output, width=200)
        agent = Agent(cfg, console, approver, AuditLog(cfg.audit_file), label=label, progress=progress)
        agent.client = FakeClient(*replies)
        return SimpleNamespace(
            agent=agent,
            client=agent.client,
            approvals=approvals,
            executed=fake_tools,
            output=output,
            audit_path=cfg.audit_file,
        )

    return factory


def tool_messages(messages) -> list[dict]:
    return [m for m in messages if isinstance(m, dict) and m["role"] == "tool"]


def roles(messages) -> list[str]:
    return [m["role"] if isinstance(m, dict) else m.role for m in messages]


def audit_records(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- Helpers -------------------------------------------------------------------------------------

def test_clean_removes_think_blocks():
    assert _clean("<think>\nhmm\n</think>\n Answer ") == "Answer"
    assert _clean(None) == ""


def test_clean_removes_reasoning_without_opening_tag():
    # Seen with qwen3:4b: it reasons even with think=False and only emits the closing tag.
    assert _clean("Okay, let's see. First I should...\n</think>\n\n**Diagnosis:** x") == "**Diagnosis:** x"


def test_truncate_keeps_head_or_tail():
    assert _truncate("abcdef", 10, "head") == "abcdef"
    assert _truncate("abcdef", 3, "head") == "abc\n...(end cut)"
    assert _truncate("abcdef", 3, "tail") == "...(start cut)\ndef"


def test_text_tool_calls_reads_json_written_in_the_answer(fake_tools):
    text = (
        'Let me look. {"name": "read_thing", "parameters": {"container": "api"}} '
        'and {"name": "explode", "arguments": {"container": "x"}}'
    )
    assert _text_tool_calls(text) == [("read_thing", {"container": "api"}), ("explode", {"container": "x"})]


def test_text_tool_calls_ignores_unknown_tools_and_broken_json(fake_tools):
    assert _text_tool_calls('{"name": "rm_rf", "parameters": {}} {broken {"name": "read_thing", "parameters": 1}') == []


# --- Loop ------------------------------------------------------------------------------------------

def test_answer_without_tools_ends_the_run(make_agent):
    t_ = make_agent(assistant("**Diagnosis:** all good"))
    assert t_.agent.run("how is it going?") == "**Diagnosis:** all good"
    (call,) = t_.client.calls
    assert call["think"] is False
    assert call["options"]["temperature"] == agent_module.TEMPERATURE
    assert "tools" in call


def test_tool_result_is_sent_back_to_the_model(make_agent):
    t_ = make_agent(assistant(calls=[("read_thing", {"container": "api"})]), assistant("done"))
    assert t_.agent.run("investigate api") == "done"
    assert t_.executed == [("read_thing", "api")]
    assert tool_messages(t_.client.calls[1]["messages"]) == [
        {"role": "tool", "tool_name": "read_thing", "content": "data from api"}
    ]


def test_tool_call_written_as_text_is_executed(make_agent):
    t_ = make_agent(assistant('{"name": "read_thing", "parameters": {"container": "api"}}'), assistant("done"))
    assert t_.agent.run("investigate") == "done"
    assert t_.executed == [("read_thing", "api")]


def test_denied_action_is_not_executed(make_agent):
    t_ = make_agent(assistant(calls=[("change_thing", {"container": "api"})]), assistant("done"), approve=False)
    t_.agent.run("fix it")
    assert t_.approvals == [("change_thing", {"container": "api"})]
    assert t_.executed == []
    assert tool_messages(t_.client.calls[1]["messages"])[0]["content"] == t("prompt.action_denied")


def test_approved_action_is_executed(make_agent):
    t_ = make_agent(assistant(calls=[("change_thing", {"container": "api"})]), assistant("done"), approve=True)
    t_.agent.run("fix it")
    assert t_.executed == [("change_thing", "api")]


def test_read_tools_never_ask_for_approval(make_agent):
    t_ = make_agent(assistant(calls=[("read_thing", {"container": "api"})]), assistant("done"))
    t_.agent.run("look")
    assert t_.approvals == []


def test_unknown_tool_returns_error_with_available_tools(make_agent):
    t_ = make_agent(assistant(calls=[("delete_everything", {})]), assistant("done"))
    t_.agent.run("x")
    content = tool_messages(t_.client.calls[1]["messages"])[0]["content"]
    assert "delete_everything" in content and "read_thing" in content


def test_tool_failure_becomes_text_for_the_model(make_agent):
    t_ = make_agent(assistant(calls=[("explode", {"container": "api"})]), assistant("done"))
    assert t_.agent.run("x") == "done"
    assert tool_messages(t_.client.calls[1]["messages"])[0]["content"] == "Error: docker is down"


def test_long_tool_output_is_truncated(make_agent):
    t_ = make_agent(assistant(calls=[("read_thing", {"container": "x" * 100})]), assistant("done"))
    t_.agent.cfg.max_tool_output = 20
    t_.agent.run("x")
    assert tool_messages(t_.client.calls[1]["messages"])[0]["content"].endswith("...(end cut)")


def test_step_limit_forces_a_final_answer_without_tools(make_agent):
    call = assistant(calls=[("read_thing", {"container": "api"})])
    t_ = make_agent(call, call, assistant("summary"), max_steps=2)
    assert t_.agent.run("x") == "summary"
    assert len(t_.client.calls) == 3
    assert "tools" not in t_.client.calls[-1]
    assert t_.client.calls[-1]["messages"][-1]["content"] == t("prompt.step_limit")


# --- Secrets ----------------------------------------------------------------------------------------

def test_tool_output_is_redacted_before_reaching_the_model(make_agent):
    t_ = make_agent(assistant(calls=[("leak", {"container": "api"})]), assistant("done"))
    t_.agent.run("x")
    content = tool_messages(t_.client.calls[1]["messages"])[0]["content"]
    assert FAKE_TOKEN not in content
    assert MASK in content


def test_tool_output_is_redacted_in_the_audit_log(make_agent):
    t_ = make_agent(assistant(calls=[("leak", {"container": "api"})]), assistant("done"))
    t_.agent.run("x")
    assert FAKE_TOKEN not in t_.audit_path.read_text(encoding="utf-8")


# --- Evidence requirement ----------------------------------------------------------------------------

def test_answer_without_evidence_is_rejected_when_required(make_agent):
    t_ = make_agent(assistant("made up"), assistant(calls=[("read_thing", {"container": "api"})]), assistant("done"))
    assert t_.agent.run("investigate", require_evidence=True) == "done"
    assert t_.client.calls[1]["messages"][-1]["content"] == t("prompt.evidence")


def test_evidence_is_demanded_only_once(make_agent):
    t_ = make_agent(assistant("a"), assistant("b"))
    assert t_.agent.run("investigate", require_evidence=True) == "b"


def test_evidence_is_not_required_by_default(make_agent):
    t_ = make_agent(assistant("direct answer"))
    assert t_.agent.run("hi") == "direct answer"


# --- Ollama errors -----------------------------------------------------------------------------------

def test_model_without_think_support_is_retried_without_the_flag(make_agent):
    error = ollama.ResponseError('"llama3.2:3b" does not support thinking', 400)
    t_ = make_agent(error, assistant("ok"), assistant("again"))
    assert t_.agent.run("x") == "ok"
    assert "think" not in t_.client.calls[1]
    t_.agent.run("y")
    assert "think" not in t_.client.calls[2]


def test_other_errors_propagate_and_roll_back_history(make_agent):
    t_ = make_agent(ollama.ResponseError("model 'x' not found", 404))
    with pytest.raises(ollama.ResponseError):
        t_.agent.run("x")
    assert roles(t_.agent.messages) == ["system"]


# --- Language, labels and progress ---------------------------------------------------------------------

def test_system_prompt_follows_the_language(make_agent):
    assert "answer in English" in make_agent().agent.messages[0]["content"]
    i18n.set_language("pt-BR")
    assert "responda em português" in make_agent().agent.messages[0]["content"]


def test_output_lines_are_prefixed_with_the_label(make_agent):
    t_ = make_agent(assistant(calls=[("read_thing", {"container": "api"})]), assistant("done"), label="api")
    t_.agent.run("x")
    assert "[api] → read_thing" in t_.output.getvalue()


def test_progress_indicator_wraps_every_model_call(make_agent):
    seen = []

    @contextmanager
    def progress(message):
        seen.append(message)
        yield

    t_ = make_agent(assistant(calls=[("read_thing", {"container": "a"})]), assistant("done"), progress=progress)
    t_.agent.run("x")
    assert seen == [t("agent.thinking")] * 2


# --- History and audit ---------------------------------------------------------------------------------

def test_history_keeps_only_last_turns(make_agent):
    t_ = make_agent(*[assistant(f"r{i}") for i in range(5)])
    for i in range(5):
        t_.agent.run(f"question {i}")
    assert roles(t_.agent.messages).count("user") == agent_module.HISTORY_TURNS
    assert roles(t_.agent.messages)[0] == "system"


def test_reset_clears_history(make_agent):
    t_ = make_agent(assistant("r"))
    t_.agent.run("x")
    t_.agent.reset()
    assert roles(t_.agent.messages) == ["system"]


def test_audit_log_records_the_whole_run(make_agent):
    t_ = make_agent(assistant(calls=[("change_thing", {"container": "api"})]), assistant("done"), approve=False)
    t_.agent.run("fix it")
    assert [r["event"] for r in audit_records(t_.audit_path)] == ["task", "approval", "answer"]


def test_audit_events_share_a_run_id_and_subject(make_agent):
    t_ = make_agent(assistant("a"), assistant("b"), label="api")
    t_.agent.run("first")
    t_.agent.run("second")
    records = audit_records(t_.audit_path)
    assert {r["subject"] for r in records} == {"api"}
    first, second = records[0]["run"], records[2]["run"]
    assert records[1]["run"] == first and records[3]["run"] == second and first != second
