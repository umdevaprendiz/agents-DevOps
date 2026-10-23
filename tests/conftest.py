"""Fixtures compartilhadas. Os testes de unidade não precisam de Docker nem de Ollama rodando."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from ollama import Message

NOW = datetime.now(timezone.utc)


def docker_time(moment: datetime) -> str:
    """Formata a data como o Docker: nanossegundos e sufixo Z."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def assistant(content: str = "", calls: list[tuple[str, dict]] | None = None) -> Message:
    """Mensagem do modelo. calls = [(nome_da_ferramenta, argumentos), ...]."""
    tool_calls = [Message.ToolCall(function=Message.ToolCall.Function(name=n, arguments=a)) for n, a in calls or []]
    return Message(role="assistant", content=content, tool_calls=tool_calls or None)


class FakeClient:
    """Substitui ollama.Client: devolve respostas roteirizadas e registra cada chamada."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(message=reply)


@pytest.fixture
def make_info():
    """Fabrica o dicionário devolvido por docker_tools._summarize, com valores de um container saudável."""

    def factory(**overrides) -> dict:
        info = {
            "name": "app",
            "status": "running",
            "exit_code": 0,
            "oom_killed": False,
            "error": None,
            "started_at": docker_time(NOW - timedelta(hours=1)),
            "finished_at": "0001-01-01T00:00:00Z",
            "restart_count": 0,
            "health": None,
            "health_failing_streak": None,
        }
        info.update(overrides)
        return info

    return factory
