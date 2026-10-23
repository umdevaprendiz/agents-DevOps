"""Tools the model can call, grouped in a Toolbox.

- Docker tools: read containers; actions (restart/start/stop) always need human approval.
- Workspace tools: read project files and git state (read-only, confined, no secret files).
- propose_change: writes a suggestion to its own git branch; the operator decides with /apply or /pr.

Descriptions stay in English: models follow English tool specs most reliably.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from . import diagnostics
from . import docker_tools as dk
from .i18n import t
from .proposals import ProposalStore
from .workspace import Workspace


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


class Toolbox:
    """The tools one agent can use."""

    def __init__(self, tools: list[Tool]):
        self.by_name = {tool.name: tool for tool in tools}
        self.schemas = [tool.schema() for tool in tools]

    def get(self, name: str) -> Tool | None:
        return self.by_name.get(name)

    def names(self) -> list[str]:
        return list(self.by_name)


def _to_text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def _string(description: str) -> dict:
    return {"type": "string", "description": description}


def _integer(description: str) -> dict:
    return {"type": "integer", "description": description}


CONTAINER = _string("Container name, as shown by list_containers")


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


# --- Docker ------------------------------------------------------------------------------------------

DOCKER_TOOLS: list[Tool] = [
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
        params={"container": CONTAINER, "tail": _integer("Number of lines (default 80, max 500)")},
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


# --- Workspace (read-only) ----------------------------------------------------------------------------

def workspace_tools(workspace: Workspace) -> list[Tool]:
    path = _string("File path relative to the project root, e.g. 'docker-compose.yml' or 'src/app.py'")
    return [
        Tool(
            name="list_files",
            description="Lists project files (respects .gitignore; secret files are hidden). "
            "Optional glob such as '*.yml', 'Dockerfile' or 'src/*'.",
            params={"pattern": _string("Glob pattern (default '*')")},
            required=(),
            func=workspace.list_files,
        ),
        Tool(
            name="read_file",
            description="Reads a project file. Each line is prefixed with its number as '12| '; "
            "that prefix is NOT part of the file.",
            params={"path": path, "start_line": _integer("First line (default 1)"),
                    "max_lines": _integer("How many lines (default 200, max 500)")},
            required=("path",),
            func=workspace.read_file,
        ),
        Tool(
            name="search_files",
            description="Searches project files with a regular expression. Returns 'path:line: text'.",
            params={"pattern": _string("Regular expression or plain text"),
                    "glob": _string("Only files matching this glob (default '*')")},
            required=("pattern",),
            func=workspace.search,
        ),
        Tool(name="git_status", description="Current branch and uncommitted files.", params={}, required=(),
             func=workspace.git_status),
        Tool(name="git_log", description="Recent commits.", params={"limit": _integer("How many (default 10)")},
             required=(), func=workspace.git_log),
        Tool(name="git_diff", description="Uncommitted changes in the working tree, optionally for one file.",
             params={"path": path}, required=(), func=workspace.git_diff, keep="head"),
    ]


def diagnostics_tool(workspace: Workspace) -> Tool:
    return Tool(
        name="collect_diagnostics",
        description="Starting point for debugging: containers with problems and their recent errors, "
        "error lines in project log files, and the project's infrastructure files "
        "(Dockerfiles, compose, CI, Kubernetes, Terraform...).",
        params={},
        required=(),
        func=partial(diagnostics.collect, workspace),
    )


# --- Change proposals ---------------------------------------------------------------------------------

_EDITS_SCHEMA = {
    "type": "array",
    "description": "Edits to apply. old_text must be copied exactly from the file (without the '12| ' "
    "line-number prefix) and appear only once; use old_text='' to create a new file.",
    "items": {
        "type": "object",
        "properties": {"path": _string("File path"), "old_text": _string("Exact text to replace"),
                       "new_text": _string("Replacement text")},
        "required": ["path", "old_text", "new_text"],
    },
}


def proposal_tool(store: ProposalStore) -> Tool:
    def propose_change(title: str, explanation: str, edits) -> str:
        proposal = store.create(title, explanation, edits)
        return t("proposal.created", id=proposal.id, branch=proposal.branch)

    return Tool(
        name="propose_change",
        description="Proposes a file change on a new git branch without touching the operator's files. "
        "The operator reviews it and decides. Only propose changes that are really necessary: "
        "no refactors, no style changes, never secrets.",
        params={"title": _string("Short title, like a commit message"),
                "explanation": _string("Why the change is needed and what it fixes"),
                "edits": _EDITS_SCHEMA},
        required=("title", "explanation", "edits"),
        func=propose_change,
    )


def build_toolbox(workspace: Workspace | None = None, proposals: ProposalStore | None = None) -> Toolbox:
    tools = list(DOCKER_TOOLS)
    if workspace is not None:
        tools += [*workspace_tools(workspace), diagnostics_tool(workspace)]
    if proposals is not None:
        tools.append(proposal_tool(proposals))
    return Toolbox(tools)
