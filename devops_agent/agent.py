"""Loop do agente: o modelo escolhe ferramentas, o agente executa e devolve o resultado."""
from __future__ import annotations

import json
import re
from typing import Callable, Iterator

import ollama
from rich.console import Console
from rich.markup import escape

from . import prompts
from .audit import AuditLog
from .config import Config
from .tools import TOOL_SCHEMAS, TOOLS_BY_NAME, Tool

Approver = Callable[[Tool, dict], bool]
ToolCall = tuple[str, dict]

HISTORY_TURNS = 3
TEMPERATURE = 0.1
AUDIT_OUTPUT_CHARS = 500

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


# --- funções auxiliares ---------------------------------------------------------

def _clean(text: str | None) -> str:
    """Remove blocos <think> e espaços extras da resposta do modelo."""
    return _THINK_RE.sub("", text or "").strip()


def _truncate(text: str, limit: int, keep: str) -> str:
    if len(text) <= limit:
        return text
    if keep == "tail":
        return "...(início cortado)\n" + text[-limit:]
    return text[:limit] + "\n...(final cortado)"


def _role(message) -> str:
    return message["role"] if isinstance(message, dict) else message.role


def _native_tool_calls(message) -> list[ToolCall]:
    return [(c.function.name, dict(c.function.arguments or {})) for c in message.tool_calls or []]


def _text_tool_calls(content: str) -> list[ToolCall]:
    """Modelos pequenos às vezes escrevem a chamada como JSON no texto em vez de usar tool_calls.
    Ex.: {"name": "inspect_container", "parameters": {"container": "api"}}"""
    return [call for obj in _json_objects(content) if (call := _as_tool_call(obj))]


def _json_objects(text: str) -> Iterator[dict]:
    """Devolve cada objeto JSON válido encontrado no meio do texto."""
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


def _as_tool_call(obj: dict) -> ToolCall | None:
    args = obj.get("parameters") or obj.get("arguments") or {}
    if obj.get("name") in TOOLS_BY_NAME and isinstance(args, dict):
        return obj["name"], args
    return None


# --- agente -------------------------------------------------------------------

class Agent:
    def __init__(self, cfg: Config, console: Console, approver: Approver, audit: AuditLog):
        self.cfg = cfg
        self.console = console
        self.approver = approver
        self.audit = audit
        self.client = ollama.Client(host=cfg.ollama_host)
        self._send_think = True
        self.reset()

    def reset(self) -> None:
        self.messages: list = [{"role": "system", "content": prompts.SYSTEM_PROMPT}]

    def run(self, task: str, require_evidence: bool = False) -> str:
        """Resolve uma tarefa e devolve a resposta final do modelo.
        Com require_evidence, uma resposta dada sem usar ferramentas é recusada uma vez."""
        snapshot = len(self.messages)
        try:
            return self._solve(task, require_evidence)
        except BaseException:
            # Falhou ou foi interrompido: desfaz a rodada para não deixar o histórico pela metade.
            del self.messages[snapshot:]
            raise

    # --- loop principal ---

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

    def _demand_evidence(self) -> None:
        """Modelos pequenos às vezes inventam a saída das ferramentas em vez de chamá-las."""
        self._show_note("resposta sem evidências recusada; pedindo investigação")
        self.messages.append({"role": "user", "content": prompts.EVIDENCE_PROMPT})

    def _start(self, task: str) -> None:
        self.messages.append({"role": "user", "content": task})
        self._trim_history()
        self.audit.log("task", task=task, model=self.cfg.model)

    def _step(self) -> str | None:
        """Uma rodada: pergunta ao modelo e executa as ferramentas pedidas.
        Devolve a resposta final quando o modelo não pede mais ferramentas."""
        message = self._ask_model(with_tools=True)
        content = _clean(message.content)
        calls = _native_tool_calls(message)
        if calls and content:
            self._show_note(content)
        calls = calls or _text_tool_calls(content)
        if not calls:
            return content
        self._run_calls(calls)
        return None

    def _run_calls(self, calls: list[ToolCall]) -> None:
        for name, args in calls:
            result = self._execute(name, args)
            self.messages.append({"role": "tool", "tool_name": name, "content": result})

    def _force_answer(self) -> str:
        self.messages.append({"role": "user", "content": prompts.STEP_LIMIT_PROMPT})
        return _clean(self._ask_model(with_tools=False).content)

    def _finish(self, answer: str) -> str:
        self.audit.log("answer", answer=answer)
        return answer

    # --- conversa com o modelo ---

    def _ask_model(self, with_tools: bool):
        """Chama o modelo e guarda a resposta no histórico."""
        with self.console.status("[dim]pensando...[/]", spinner="dots"):
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
            kwargs["tools"] = TOOL_SCHEMAS
        if self._send_think:
            kwargs["think"] = False  # modelos como qwen3 respondem bem mais rápido sem o modo "thinking"
        return kwargs

    def _chat(self, kwargs: dict):
        try:
            return self.client.chat(**kwargs).message
        except ollama.ResponseError as error:
            if not self._think_unsupported(error, kwargs):
                raise
            # Modelo sem suporte a "think": tenta de novo sem o parâmetro.
            self._send_think = False
            kwargs.pop("think")
            return self.client.chat(**kwargs).message

    @staticmethod
    def _think_unsupported(error: Exception, kwargs: dict) -> bool:
        return "think" in kwargs and "think" in str(error).lower()

    # --- execução de ferramentas ---

    def _execute(self, name: str, args: dict) -> str:
        tool = TOOLS_BY_NAME.get(name)
        if tool is None:
            return self._unknown_tool(name)
        self._show_call(name, args)
        if tool.needs_approval and not self._approve(tool, args):
            return prompts.ACTION_DENIED
        return _truncate(self._invoke(tool, args), self.cfg.max_tool_output, tool.keep)

    def _unknown_tool(self, name: str) -> str:
        self.console.print(f"[red]✗ ferramenta desconhecida: {escape(name)}[/]")
        return prompts.unknown_tool(name, list(TOOLS_BY_NAME))

    def _approve(self, tool: Tool, args: dict) -> bool:
        approved = self.approver(tool, args)
        self.audit.log("approval", tool=tool.name, args=args, approved=approved)
        if not approved:
            self.console.print("[yellow]  ação negada[/]")
        return approved

    def _invoke(self, tool: Tool, args: dict) -> str:
        try:
            result, ok = tool.run(args), True
        except Exception as error:  # o erro volta como texto para o modelo poder se corrigir
            result, ok = f"Erro: {error}", False
            self.console.print(f"[red]  {escape(result)}[/]")
        self.audit.log("tool", tool=tool.name, args=args, ok=ok, output=result[:AUDIT_OUTPUT_CHARS])
        return result

    # --- terminal ---

    def _show_call(self, name: str, args: dict) -> None:
        shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
        self.console.print(f"[cyan]→ {name}({escape(shown)})[/]")

    def _show_note(self, text: str) -> None:
        self.console.print(f"[italic dim]{escape(text)}[/]")

    # --- histórico ---

    def _trim_history(self, keep_turns: int = HISTORY_TURNS) -> None:
        """Mantém só as últimas conversas para não estourar o contexto do modelo."""
        user_turns = [i for i, m in enumerate(self.messages) if _role(m) == "user"]
        if len(user_turns) > keep_turns:
            self.messages = [self.messages[0], *self.messages[user_turns[-keep_turns]:]]
