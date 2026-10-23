"""Loop do agente: o modelo escolhe ferramentas, o agente executa e devolve o resultado."""
from __future__ import annotations

import re
from typing import Callable

import ollama
from rich.console import Console
from rich.markup import escape

from .audit import AuditLog
from .config import Config
from .tools import TOOLS, TOOLS_BY_NAME, Tool

SYSTEM_PROMPT = """Você é um agente de DevOps que cuida dos containers Docker desta máquina.

Regras:
1. Investigue antes de concluir. Use as ferramentas list_containers, inspect_container, get_container_logs e get_container_stats.
2. Baseie-se só no que as ferramentas retornaram. Não invente nomes de containers, logs ou números.
3. Só proponha restart/start/stop quando isso puder resolver. Se a causa for configuração errada, variável de ambiente faltando, bug no código ou dependência fora do ar, reiniciar não resolve: explique o que a pessoa precisa corrigir.
4. Ações que alteram containers pedem aprovação humana. Se for negada, não repita; sugira alternativas.
5. Seja breve.

Referência de exit codes: 0 = terminou normalmente; 1 = erro da aplicação; 2 = erro de uso/configuração; 125-127 = erro do Docker ou comando não encontrado; 137 = morto com SIGKILL (geralmente falta de memória, confira oom_killed); 139 = segfault; 143 = parado com SIGTERM.

Quando terminar, responda em português neste formato:
**Diagnóstico:** o que está acontecendo
**Causa provável:** por quê, citando a evidência (linha de log, exit code...)
**Ação:** o que você fez ou o que recomenda fazer"""

Approver = Callable[[Tool, dict], bool]

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _clean(text: str | None) -> str:
    return _THINK_RE.sub("", text or "").strip()


def _truncate(text: str, limit: int, keep: str) -> str:
    if len(text) <= limit:
        return text
    if keep == "tail":
        return "...(início cortado)\n" + text[-limit:]
    return text[:limit] + "\n...(final cortado)"


def _role(message) -> str:
    return message["role"] if isinstance(message, dict) else message.role


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
        self.messages: list = [{"role": "system", "content": SYSTEM_PROMPT}]

    def run(self, task: str) -> str:
        snapshot = len(self.messages)
        try:
            return self._run(task)
        except BaseException:
            # Se a execução falhar ou for interrompida, desfaz a rodada para não deixar o histórico pela metade.
            del self.messages[snapshot:]
            raise

    def _run(self, task: str) -> str:
        self.messages.append({"role": "user", "content": task})
        self._trim_history()
        self.audit.log("task", task=task, model=self.cfg.model)

        for _ in range(self.cfg.max_steps):
            msg = self._chat(with_tools=True)
            self.messages.append(msg)
            if not msg.tool_calls:
                return self._finish(msg.content)
            if note := _clean(msg.content):
                self.console.print(f"[italic dim]{escape(note)}[/]")
            for call in msg.tool_calls:
                name = call.function.name
                result = self._execute(name, dict(call.function.arguments or {}))
                self.messages.append({"role": "tool", "tool_name": name, "content": result})

        self.messages.append(
            {"role": "user", "content": "Limite de passos atingido. Responda agora com o que já descobriu, no formato pedido."}
        )
        msg = self._chat(with_tools=False)
        self.messages.append(msg)
        return self._finish(msg.content)

    def _finish(self, content: str | None) -> str:
        answer = _clean(content)
        self.audit.log("answer", answer=answer)
        return answer

    def _chat(self, with_tools: bool):
        kwargs = {
            "model": self.cfg.model,
            "messages": self.messages,
            "options": {"temperature": 0.1, "num_ctx": self.cfg.num_ctx},
        }
        if with_tools:
            kwargs["tools"] = [t.schema() for t in TOOLS]
        if self._send_think:
            kwargs["think"] = False  # modelos como qwen3 respondem bem mais rápido sem o modo "thinking"
        with self.console.status("[dim]pensando...[/]", spinner="dots"):
            try:
                return self.client.chat(**kwargs).message
            except ollama.ResponseError as e:
                if "think" not in str(e).lower() or "think" not in kwargs:
                    raise
                # Modelo sem suporte a "think": tenta de novo sem o parâmetro.
                self._send_think = False
                del kwargs["think"]
                return self.client.chat(**kwargs).message

    def _execute(self, name: str, args: dict) -> str:
        tool = TOOLS_BY_NAME.get(name)
        shown = escape(", ".join(f"{k}={v!r}" for k, v in args.items()))
        if tool is None:
            self.console.print(f"[red]✗ ferramenta desconhecida: {escape(name)}[/]")
            return f"Erro: a ferramenta '{name}' não existe. Disponíveis: {', '.join(TOOLS_BY_NAME)}."

        self.console.print(f"[cyan]→ {name}({shown})[/]")
        if tool.needs_approval:
            approved = self.approver(tool, args)
            self.audit.log("approval", tool=name, args=args, approved=approved)
            if not approved:
                self.console.print("[yellow]  ação negada[/]")
                return "Ação NEGADA pelo operador. Não tente executá-la de novo; explique o que ele pode fazer."

        try:
            result, ok = tool.run(args), True
        except Exception as e:  # o erro volta como texto para o modelo poder se corrigir
            result, ok = f"Erro: {e}", False
            self.console.print(f"[red]  {escape(result)}[/]")
        self.audit.log("tool", tool=name, args=args, ok=ok, output=result[:500])
        return _truncate(result, self.cfg.max_tool_output, tool.keep)

    def _trim_history(self, keep_turns: int = 3) -> None:
        """Mantém só as últimas conversas para não estourar o contexto do modelo."""
        user_turns = [i for i, m in enumerate(self.messages) if _role(m) == "user"]
        if len(user_turns) > keep_turns:
            self.messages = [self.messages[0], *self.messages[user_turns[-keep_turns]:]]
