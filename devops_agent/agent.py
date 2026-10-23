"""Agent loop: the model picks tools, the agent runs them and feeds the results back."""
from __future__ import annotations

import json
import re
import uuid
from contextlib import AbstractContextManager, nullcontext
from typing import Callable, Iterator

import ollama
from rich.console import Console
from rich.markup import escape

from .audit import AuditLog
from .config import Config
from .i18n import t
from .redaction import redact
from .tools import Tool, Toolbox, build_toolbox

Approver = Callable[[Tool, dict], bool]
Progress = Callable[[str], AbstractContextManager]
ToolCall = tuple[str, dict]

HISTORY_TURNS = 3
TEMPERATURE = 0.1
AUDIT_OUTPUT_CHARS = 500

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_END = "</think>"


# --- Helpers ----------------------------------------------------------------------------------------

def _clean(text: str | None) -> str:
    """Removes the model's reasoning and surrounding whitespace from its answer."""
    text = _THINK_RE.sub("", text or "")
    if _THINK_END in text:
        # Thinking models (e.g. qwen3) may reason even with think=False and omit the opening tag.
        text = text.rsplit(_THINK_END, 1)[1]
    return text.strip()


def _truncate(text: str, limit: int, keep: str) -> str:
    if len(text) <= limit:
        return text
    if keep == "tail":
        return t("text.truncated_start") + "\n" + text[-limit:]
    return text[:limit] + "\n" + t("text.truncated_end")


def _role(message) -> str:
    return message["role"] if isinstance(message, dict) else message.role


def _native_tool_calls(message) -> list[ToolCall]:
    return [(c.function.name, dict(c.function.arguments or {})) for c in message.tool_calls or []]


def _text_tool_calls(content: str, known: dict) -> list[ToolCall]:
    """Small models sometimes write the call as JSON in the text instead of using tool_calls.
    E.g.: {"name": "inspect_container", "parameters": {"container": "api"}}"""
    return [call for obj in _json_objects(content) if (call := _as_tool_call(obj, known))]


def _json_objects(text: str) -> Iterator[dict]:
    """Yields every valid JSON object found inside the text."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(obj, dict):
            yield obj
        start = text.find("{", end)


def _as_tool_call(obj: dict, known: dict) -> ToolCall | None:
    args = obj.get("parameters") or obj.get("arguments") or {}
    if obj.get("name") in known and isinstance(args, dict):
        return obj["name"], args
    return None


def _no_progress(message: str) -> AbstractContextManager:
    return nullcontext()


# --- Agent ------------------------------------------------------------------------------------------

class Agent:
    """One conversation with the model. Not thread-safe: create one Agent per investigation."""

    def __init__(
        self,
        cfg: Config,
        console: Console,
        approver: Approver,
        audit: AuditLog,
        label: str | None = None,
        progress: Progress | None = None,
        tools: Toolbox | None = None,
    ):
        self.cfg = cfg
        self.console = console
        self.approver = approver
        self.audit = audit
        self.label = label
        self.tools = tools or build_toolbox()
        self.client = ollama.Client(host=cfg.ollama_host)
        self._progress = progress or _no_progress
        self._send_think = True
        self._run_id: str | None = None
        self.reset()

    def reset(self) -> None:
        self.messages: list = [{"role": "system", "content": t("prompt.system")}]

    def run(self, task: str, require_evidence: bool = False) -> str:
        """Solves a task and returns the model's final answer.
        With require_evidence, an answer given without using any tool is rejected once."""
        snapshot = len(self.messages)
        self._run_id = uuid.uuid4().hex[:8]
        try:
            return self._solve(task, require_evidence)
        except BaseException:
            # Failed or interrupted: undo the round so the history is never left half-written.
            del self.messages[snapshot:]
            raise

    # --- Main loop ---

    def _solve(self, task: str, require_evidence: bool) -> str:
        self._start(task)
        used_tools = False
        for _ in range(self.cfg.max_steps):
            answer = self._step()
            if answer is None:
                used_tools = True
            elif require_evidence and not used_tools:
                self._demand_evidence()
                require_evidence = False
            else:
                return self._finish(answer)
        return self._finish(self._force_answer())

    def _start(self, task: str) -> None:
        self.messages.append({"role": "user", "content": task})
        self._trim_history()
        self._audit("task", task=task, model=self.cfg.model)

    def _step(self) -> str | None:
        """One round: asks the model and runs the requested tools.
        Returns the final answer when the model stops asking for tools."""
        message = self._ask_model(with_tools=True)
        content = _clean(message.content)
        calls = _native_tool_calls(message)
        if calls and content:
            self._print(f"[italic dim]{escape(content)}[/]")
        calls = calls or _text_tool_calls(content, self.tools.by_name)
        if not calls:
            return content
        self._run_calls(calls)
        return None

    def _run_calls(self, calls: list[ToolCall]) -> None:
        for name, args in calls:
            result = self._execute(name, args)
            self.messages.append({"role": "tool", "tool_name": name, "content": result})

    def _demand_evidence(self) -> None:
        """Small models sometimes invent tool outputs instead of calling the tools."""
        self._print(f"[italic dim]{escape(t('agent.evidence_rejected'))}[/]")
        self.messages.append({"role": "user", "content": t("prompt.evidence")})

    def _force_answer(self) -> str:
        self.messages.append({"role": "user", "content": t("prompt.step_limit")})
        return _clean(self._ask_model(with_tools=False).content)

    def _finish(self, answer: str) -> str:
        self._audit("answer", answer=answer)
        return answer

    # --- Talking to the model ---

    def _ask_model(self, with_tools: bool):
        """Calls the model and stores its answer in the history."""
        with self._progress(t("agent.thinking")):
            message = self._chat(self._chat_kwargs(with_tools))
        self.messages.append(message)
        return message

    def _chat_kwargs(self, with_tools: bool) -> dict:
        kwargs = {
            "model": self.cfg.model,
            "messages": self.messages,
            "options": {"temperature": TEMPERATURE, "num_ctx": self.cfg.num_ctx},
        }
        if with_tools:
            kwargs["tools"] = self.tools.schemas
        if self._send_think:
            kwargs["think"] = False  # models like qwen3 answer much faster without "thinking" mode
        return kwargs

    def _chat(self, kwargs: dict):
        try:
            return self.client.chat(**kwargs).message
        except ollama.ResponseError as error:
            if not self._think_unsupported(error, kwargs):
                raise
            # The model has no "think" support: retry without the parameter.
            self._send_think = False
            kwargs.pop("think")
            return self.client.chat(**kwargs).message

    @staticmethod
    def _think_unsupported(error: Exception, kwargs: dict) -> bool:
        return "think" in kwargs and "think" in str(error).lower()

    # --- Running tools ---

    def _execute(self, name: str, args: dict) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return self._unknown_tool(name)
        self._show_call(name, args)
        if tool.needs_approval and not self._approve(tool, args):
            return t("prompt.action_denied")
        return _truncate(self._invoke(tool, args), self.cfg.max_tool_output, tool.keep)

    def _unknown_tool(self, name: str) -> str:
        self._print(f"[red]{escape(t('agent.unknown_tool', name=name))}[/]")
        return t("prompt.unknown_tool", name=name, available=", ".join(self.tools.names()))

    def _approve(self, tool: Tool, args: dict) -> bool:
        approved = self.approver(tool, args)
        self._audit("approval", tool=tool.name, args=args, approved=approved)
        if not approved:
            self._print(f"[yellow]  {escape(t('agent.denied'))}[/]")
        return approved

    def _invoke(self, tool: Tool, args: dict) -> str:
        """Runs the tool and redacts secrets before the output reaches the model or the audit log."""
        try:
            result, ok = tool.run(args), True
        except Exception as error:  # the error goes back as text so the model can correct itself
            result, ok = t("agent.tool_error", error=error), False
        result = redact(result)
        if not ok:
            self._print(f"[red]  {escape(result)}[/]")
        self._audit("tool", tool=tool.name, args=args, ok=ok, output=result[:AUDIT_OUTPUT_CHARS])
        return result

    # --- Output and audit ---

    def _show_call(self, name: str, args: dict) -> None:
        shown = ", ".join(f"{key}={value!r}" for key, value in args.items())
        self._print(f"[cyan]→ {name}({escape(shown)})[/]")

    def _print(self, markup: str) -> None:
        """Prints a line, prefixed with the label when several investigations run in parallel."""
        prefix = f"[bold]{escape('[' + self.label + ']')}[/] " if self.label else ""
        self.console.print(prefix + markup)

    def _audit(self, event: str, **data) -> None:
        self.audit.log(event, run=self._run_id, subject=self.label, **data)

    # --- History ---

    def _trim_history(self, keep_turns: int = HISTORY_TURNS) -> None:
        """Keeps only the latest turns so the model context does not overflow."""
        user_turns = [i for i, m in enumerate(self.messages) if _role(m) == "user"]
        if len(user_turns) > keep_turns:
            self.messages = [self.messages[0], *self.messages[user_turns[-keep_turns]:]]
