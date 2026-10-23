"""Tools the model can call.

To give the agent a new capability, add a Tool to TOOLS. Anything that changes state
must be created with _action_tool, which always requires human approval.
Descriptions stay in English: models follow English tool specs most reliably.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from . import docker_tools as dk
from .i18n import t


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: dict[str, dict]
    required: tuple[str, ...]
    func: Callable[..., Any]
    needs_approval: bool = False
    keep: str = "head"  # part kept when the output is too long: "head" or "tail"

    def schema(self) -> dict:
        """Tool format accepted by the Ollama chat API."""
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
        """Drops parameters the model invented and empty values."""
        return {k: v for k, v in (args or {}).items() if k in self.params and v not in (None, "")}

    def _check_required(self, kwargs: dict) -> None:
        missing = [name for name in self.required if name not in kwargs]
        if missing:
            raise ValueError(t("tools.missing_params", names=", ".join(missing)))


def _to_text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


CONTAINER = {"type": "string", "description": "Container name, as shown by list_containers"}


def _action_tool(name: str, description: str, func: Callable[[str], str]) -> Tool:
    """A tool that changes a container: always requires human approval."""
    return Tool(
        name=name,
        description=f"{description} Requires human approval.",
        params={"container": CONTAINER},
        required=("container",),
        func=func,
        needs_approval=True,
    )


TOOLS: list[Tool] = [
    Tool(
        name="list_containers",
        description="Lists Docker containers with their state (running, exited, restarting...) and status.",
        params={"include_stopped": {"type": "boolean", "description": "Include stopped containers (default: true)"}},
        required=(),
        func=dk.list_containers,
    ),
    Tool(
        name="inspect_container",
        description="Container details: exit code, OOMKilled, healthcheck, restart policy, "
        "memory limit, ports and environment variable names.",
        params={"container": CONTAINER},
        required=("container",),
        func=dk.inspect_container,
    ),
    Tool(
        name="get_container_logs",
        description="Last log lines (stdout and stderr) of a container.",
        params={
            "container": CONTAINER,
            "tail": {"type": "integer", "description": "Number of lines (default 80, max 500)"},
        },
        required=("container",),
        func=dk.container_logs,
        keep="tail",
    ),
    Tool(
        name="get_container_stats",
        description="Current CPU, memory, network and disk usage. Without 'container', shows every running one.",
        params={"container": CONTAINER},
        required=(),
        func=dk.container_stats,
    ),
    _action_tool("restart_container", "Restarts a container.", dk.restart_container),
    _action_tool("start_container", "Starts a stopped container.", dk.start_container),
    _action_tool("stop_container", "Stops a running container.", dk.stop_container),
]

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
TOOL_SCHEMAS = [tool.schema() for tool in TOOLS]
