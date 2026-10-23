"""Ferramentas que o modelo pode chamar.

Para dar um novo poder ao agente, adicione um Tool em TOOLS.
Qualquer ferramenta que altere algo deve ser criada com _action_tool (exige aprovação).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from . import docker_tools as dk


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: dict[str, dict]
    required: tuple[str, ...]
    func: Callable[..., Any]
    needs_approval: bool = False
    keep: str = "head"  # parte mantida se a saída for grande demais ("head" ou "tail")

    def schema(self) -> dict:
        """Formato de ferramenta aceito pela API de chat do Ollama."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": self.params, "required": list(self.required)},
            },
        }

    def run(self, args: dict) -> str:
        kwargs = self._known_args(args)
        self._check_required(kwargs)
        return _to_text(self.func(**kwargs))

    def _known_args(self, args: dict | None) -> dict:
        """Ignora parâmetros que o modelo inventou e valores vazios."""
        return {k: v for k, v in (args or {}).items() if k in self.params and v not in (None, "")}

    def _check_required(self, kwargs: dict) -> None:
        missing = [name for name in self.required if name not in kwargs]
        if missing:
            raise ValueError(f"faltam parâmetros: {', '.join(missing)}")


def _to_text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


CONTAINER = {"type": "string", "description": "Nome do container, como aparece em list_containers"}


def _action_tool(name: str, description: str, func: Callable[[str], str]) -> Tool:
    """Ferramenta que altera um container: sempre exige aprovação humana."""
    return Tool(
        name=name,
        description=f"{description} Exige aprovação humana.",
        params={"container": CONTAINER},
        required=("container",),
        func=func,
        needs_approval=True,
    )


TOOLS: list[Tool] = [
    Tool(
        name="list_containers",
        description="Lista os containers Docker com estado (running, exited, restarting...) e status.",
        params={"include_stopped": {"type": "boolean", "description": "Incluir containers parados (padrão: true)"}},
        required=(),
        func=dk.list_containers,
    ),
    Tool(
        name="inspect_container",
        description="Detalhes de um container: exit code, OOMKilled, healthcheck, política de restart, "
        "limite de memória, portas e nomes das variáveis de ambiente.",
        params={"container": CONTAINER},
        required=("container",),
        func=dk.inspect_container,
    ),
    Tool(
        name="get_container_logs",
        description="Últimas linhas de log (stdout e stderr) de um container.",
        params={
            "container": CONTAINER,
            "tail": {"type": "integer", "description": "Quantidade de linhas (padrão 80, máx. 500)"},
        },
        required=("container",),
        func=dk.container_logs,
        keep="tail",
    ),
    Tool(
        name="get_container_stats",
        description="Uso atual de CPU, memória, rede e disco. Sem 'container', mostra todos os que estão rodando.",
        params={"container": CONTAINER},
        required=(),
        func=dk.container_stats,
    ),
    _action_tool("restart_container", "Reinicia um container.", dk.restart_container),
    _action_tool("start_container", "Inicia um container parado.", dk.start_container),
    _action_tool("stop_container", "Para um container em execução.", dk.stop_container),
]

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
TOOL_SCHEMAS = [tool.schema() for tool in TOOLS]
