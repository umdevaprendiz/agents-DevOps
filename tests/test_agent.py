import io
import json
from types import SimpleNamespace

import ollama
import pytest
from rich.console import Console

from devops_agent import agent as agent_module
from devops_agent import prompts
from devops_agent.agent import Agent, _clean, _text_tool_calls, _truncate
from devops_agent.audit import AuditLog
from devops_agent.config import Config
from devops_agent.tools import Tool
from tests.conftest import FakeClient, assistant

CONTAINER = {"container": {"type": "string"}}


def _explode(container):
    raise RuntimeError("docker caiu")


@pytest.fixture
def fake_tools(monkeypatch):
    """Ferramentas falsas: o agente é testado sem tocar no Docker."""
    executed = []

    def read(container):
        executed.append(("read_thing", container))
        return f"dados de {container}"

    def change(container):
        executed.append(("change_thing", container))
        return f"{container} alterado"

    tools = {
        "read_thing": Tool("read_thing", "Lê.", CONTAINER, ("container",), read),
        "change_thing": Tool("change_thing", "Altera.", CONTAINER, ("container",), change, needs_approval=True),
        "explode": Tool("explode", "Falha.", CONTAINER, ("container",), _explode),
    }
    monkeypatch.setattr(agent_module, "TOOLS_BY_NAME", tools)
    return executed


@pytest.fixture
def make_agent(tmp_path, fake_tools):
    """Cria um Agent com cliente roteirizado. Devolve agent, client, approvals, executed e audit_path."""

    def factory(*replies, approve=True, max_steps=5):
        cfg = Config()
        cfg.max_steps = max_steps
        cfg.audit_file = tmp_path / "audit.jsonl"
        approvals = []

        def approver(tool, args):
            approvals.append((tool.name, args))
            return approve

        agent = Agent(cfg, Console(file=io.StringIO()), approver, AuditLog(cfg.audit_file))
        agent.client = FakeClient(*replies)
        return SimpleNamespace(
            agent=agent, client=agent.client, approvals=approvals, executed=fake_tools, audit_path=cfg.audit_file
        )

    return factory


def tool_messages(messages) -> list[dict]:
    return [m for m in messages if isinstance(m, dict) and m["role"] == "tool"]


def roles(messages) -> list[str]:
    return [m["role"] if isinstance(m, dict) else m.role for m in messages]


# --- funções auxiliares -------------------------------------------------------------------

def test_clean_removes_think_blocks():
    assert _clean("<think>\nhmm\n</think>\n Resposta ") == "Resposta"
    assert _clean(None) == ""


def test_truncate_keeps_head_or_tail():
    assert _truncate("abcdef", 10, "head") == "abcdef"
    assert _truncate("abcdef", 3, "head") == "abc\n...(final cortado)"
    assert _truncate("abcdef", 3, "tail") == "...(início cortado)\ndef"


def test_text_tool_calls_reads_json_written_in_the_answer(fake_tools):
    text = 'Vou olhar. {"name": "read_thing", "parameters": {"container": "api"}} e {"name": "explode", "arguments": {"container": "x"}}'
    assert _text_tool_calls(text) == [("read_thing", {"container": "api"}), ("explode", {"container": "x"})]


def test_text_tool_calls_ignores_unknown_tools_and_broken_json(fake_tools):
    assert _text_tool_calls('{"name": "rm_rf", "parameters": {}} {quebrado {"name": "read_thing", "parameters": 1}') == []


# --- loop ------------------------------------------------------------------------------------

def test_answer_without_tools_ends_the_run(make_agent):
    t = make_agent(assistant("**Diagnóstico:** tudo certo"))
    assert t.agent.run("como está?") == "**Diagnóstico:** tudo certo"
    (call,) = t.client.calls
    assert call["think"] is False
    assert call["options"]["temperature"] == agent_module.TEMPERATURE
    assert "tools" in call


def test_tool_result_is_sent_back_to_the_model(make_agent):
    t = make_agent(assistant(calls=[("read_thing", {"container": "api"})]), assistant("fim"))
    assert t.agent.run("investigue a api") == "fim"
    assert t.executed == [("read_thing", "api")]
    assert tool_messages(t.client.calls[1]["messages"]) == [
        {"role": "tool", "tool_name": "read_thing", "content": "dados de api"}
    ]


def test_tool_call_written_as_text_is_executed(make_agent):
    t = make_agent(assistant('{"name": "read_thing", "parameters": {"container": "api"}}'), assistant("fim"))
    assert t.agent.run("investigue") == "fim"
    assert t.executed == [("read_thing", "api")]


def test_denied_action_is_not_executed(make_agent):
    t = make_agent(assistant(calls=[("change_thing", {"container": "api"})]), assistant("fim"), approve=False)
    t.agent.run("conserte")
    assert t.approvals == [("change_thing", {"container": "api"})]
    assert t.executed == []
    assert tool_messages(t.client.calls[1]["messages"])[0]["content"] == prompts.ACTION_DENIED


def test_approved_action_is_executed(make_agent):
    t = make_agent(assistant(calls=[("change_thing", {"container": "api"})]), assistant("fim"), approve=True)
    t.agent.run("conserte")
    assert t.executed == [("change_thing", "api")]


def test_read_tools_never_ask_for_approval(make_agent):
    t = make_agent(assistant(calls=[("read_thing", {"container": "api"})]), assistant("fim"))
    t.agent.run("olhe")
    assert t.approvals == []


def test_unknown_tool_returns_error_with_available_tools(make_agent):
    t = make_agent(assistant(calls=[("delete_everything", {})]), assistant("fim"))
    t.agent.run("x")
    content = tool_messages(t.client.calls[1]["messages"])[0]["content"]
    assert "delete_everything" in content and "read_thing" in content


def test_tool_failure_becomes_text_for_the_model(make_agent):
    t = make_agent(assistant(calls=[("explode", {"container": "api"})]), assistant("fim"))
    assert t.agent.run("x") == "fim"
    assert tool_messages(t.client.calls[1]["messages"])[0]["content"] == "Erro: docker caiu"


def test_long_tool_output_is_truncated(make_agent):
    t = make_agent(assistant(calls=[("read_thing", {"container": "x" * 100})]), assistant("fim"))
    t.agent.cfg.max_tool_output = 20
    t.agent.run("x")
    assert tool_messages(t.client.calls[1]["messages"])[0]["content"].endswith("...(final cortado)")


def test_step_limit_forces_a_final_answer_without_tools(make_agent):
    call = assistant(calls=[("read_thing", {"container": "api"})])
    t = make_agent(call, call, assistant("resumo"), max_steps=2)
    assert t.agent.run("x") == "resumo"
    assert len(t.client.calls) == 3
    assert "tools" not in t.client.calls[-1]
    assert t.client.calls[-1]["messages"][-1]["content"] == prompts.STEP_LIMIT_PROMPT


# --- exigência de evidência ----------------------------------------------------------------

def test_answer_without_evidence_is_rejected_when_required(make_agent):
    t = make_agent(assistant("inventado"), assistant(calls=[("read_thing", {"container": "api"})]), assistant("fim"))
    assert t.agent.run("investigue", require_evidence=True) == "fim"
    assert t.client.calls[1]["messages"][-1]["content"] == prompts.EVIDENCE_PROMPT


def test_evidence_is_demanded_only_once(make_agent):
    t = make_agent(assistant("a"), assistant("b"))
    assert t.agent.run("investigue", require_evidence=True) == "b"


def test_evidence_is_not_required_by_default(make_agent):
    t = make_agent(assistant("resposta direta"))
    assert t.agent.run("oi") == "resposta direta"


# --- erros do Ollama ----------------------------------------------------------------------

def test_model_without_think_support_is_retried_without_the_flag(make_agent):
    error = ollama.ResponseError('"llama3.2:3b" does not support thinking', 400)
    t = make_agent(error, assistant("ok"), assistant("de novo"))
    assert t.agent.run("x") == "ok"
    assert "think" not in t.client.calls[1]
    t.agent.run("y")
    assert "think" not in t.client.calls[2]


def test_other_errors_propagate_and_roll_back_history(make_agent):
    t = make_agent(ollama.ResponseError("model 'x' not found", 404))
    with pytest.raises(ollama.ResponseError):
        t.agent.run("x")
    assert roles(t.agent.messages) == ["system"]


# --- histórico e auditoria ------------------------------------------------------------------

def test_history_keeps_only_last_turns(make_agent):
    t = make_agent(*[assistant(f"r{i}") for i in range(5)])
    for i in range(5):
        t.agent.run(f"pergunta {i}")
    assert roles(t.agent.messages).count("user") == agent_module.HISTORY_TURNS
    assert roles(t.agent.messages)[0] == "system"


def test_reset_clears_history(make_agent):
    t = make_agent(assistant("r"))
    t.agent.run("x")
    t.agent.reset()
    assert roles(t.agent.messages) == ["system"]


def test_audit_log_records_the_whole_run(make_agent):
    t = make_agent(assistant(calls=[("change_thing", {"container": "api"})]), assistant("fim"), approve=False)
    t.agent.run("conserte")
    events = [json.loads(line)["event"] for line in t.audit_path.read_text(encoding="utf-8").splitlines()]
    assert events == ["task", "approval", "answer"]
