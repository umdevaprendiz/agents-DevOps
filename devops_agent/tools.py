"""Ferramentas que o modelo pode chamar.

Para dar um novo poder ao agente, adicione um Tool em TOOLS.
Qualquer ferramenta que altere algo deve ter needs_approval=True.
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
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": self.params, "required": list(self.required)},
            },
        }

    def run(self, args: dict) -> str:
        # Ignora parâmetros que o modelo inventou e confere os obrigatórios.
        kwargs = {k: v for k, v in (args or {}).items() if k in self.params and v not in (None, "")}
        missing = [r for r in self.required if r not in kwargs]
        if missing:
            raise ValueError(f"faltam parâmetros: {', '.join(missing)}")
        result = self.func(**kwargs)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


CONTAINER = {"type": "string", "description": "Nome do container, como aparece em list_containers"}

TOOLS: list[Tool] = [
    Tool(
        "list_containers",
        "Lista os containers Docker com estado (running, exited, restarting...) e status.",
        {"include_stopped": {"type": "boolean", "description": "Incluir containers parados (padrão: true)"}},
        (),
        dk.list_containers,
    ),
    Tool(
        "inspect_container",
        "Detalhes de um container: exit code, OOMKilled, healthcheck, política de restart, "
        "limite de memória, portas e nomes das variáveis de ambiente.",
        {"container": CONTAINER},
        ("container",),
        dk.inspect_container,
    ),
    Tool(
        "get_container_logs",
        "Últimas linhas de log (stdout e stderr) de um container.",
        {"container": CONTAINER, "tail": {"type": "integer", "description": "Quantidade de linhas (padrão 80, máx. 500)"}},
        ("container",),
        dk.container_logs,
        keep="tail",
    ),
    Tool(
        "get_container_stats",
        "Uso atual de CPU, memória, rede e disco. Sem 'container', mostra todos os que estão rodando.",
        {"container": CONTAINER},
        (),
        dk.container_stats,
    ),
    Tool(
        "restart_container",
        "Reinicia um container. Exige aprovação humana.",
        {"container": CONTAINER},
        ("container",),
        dk.restart_container,
        needs_approval=True,
    ),
    Tool(
        "start_container",
        "Inicia um container parado. Exige aprovação humana.",
        {"container": CONTAINER},
        ("container",),
        dk.start_container,
        needs_approval=True,
    ),
    Tool(
        "stop_container",
        "Para um container em execução. Exige aprovação humana.",
        {"container": CONTAINER},
        ("container",),
        dk.stop_container,
        needs_approval=True,
    ),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
