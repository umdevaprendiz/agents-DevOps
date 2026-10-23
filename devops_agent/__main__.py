"""Ponto de entrada: python -m devops_agent <comando>."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

import ollama
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, InvalidResponse

from . import docker_tools as dk
from .agent import Agent
from .audit import AuditLog
from .config import Config
from .monitor import Issue, Monitor
from .tools import Tool

# Evita erro de encoding no Windows quando a saída é redirecionada (ex.: para um arquivo).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

console = Console()


class Confirmar(Confirm):
    """Confirmação em português (s/n)."""

    choices = ["s", "n"]
    validate_error_message = "[prompt.invalid]Digite s ou n"

    def process_response(self, value: str) -> bool:
        value = value.strip().lower()
        if value in ("s", "sim", "y", "yes"):
            return True
        if value in ("n", "nao", "não", "no"):
            return False
        raise InvalidResponse(self.validate_error_message)


def ask_approval(tool: Tool, args: dict) -> bool:
    target = escape(str(args.get("container", "?")))
    console.print(
        Panel(
            f"O agente quer executar [bold]{tool.name}[/] no container [bold]{target}[/].",
            title="Aprovação necessária",
            border_style="yellow",
        )
    )
    try:
        return Confirmar.ask("Permitir?", default=False, console=console)
    except (EOFError, KeyboardInterrupt):
        return False


def show_answer(answer: str) -> None:
    console.print(Panel(Markdown(answer or "_(o modelo não respondeu)_"), title="Agente", border_style="blue"))


def run_task(agent: Agent, task: str) -> None:
    try:
        show_answer(agent.run(task))
    except ollama.ResponseError as e:
        console.print(f"[red]Erro do Ollama:[/] {escape(str(e))}")
    except (ConnectionError, OSError) as e:
        console.print(f"[red]Não consegui falar com o Ollama:[/] {escape(str(e))}")


def preflight(cfg: Config) -> bool:
    ok = True
    try:
        console.print(f"[green]✓[/] Docker {dk.server_version()}")
    except dk.DockerError as e:
        console.print(f"[red]✗ Docker indisponível:[/] {escape(str(e))}\n  Abra o Docker Desktop e tente de novo.")
        ok = False
    try:
        ollama.Client(host=cfg.ollama_host).show(cfg.model)
        console.print(f"[green]✓[/] Ollama com o modelo {cfg.model}")
    except ollama.ResponseError:
        console.print(f"[red]✗ Modelo '{cfg.model}' não encontrado.[/] Rode: [bold]ollama pull {cfg.model}[/]")
        ok = False
    except Exception as e:
        console.print(f"[red]✗ Ollama não respondeu:[/] {escape(str(e))}\n  Abra o Ollama e tente de novo.")
        ok = False
    return ok


def handle_issues(agent: Agent, issues: list[Issue]) -> None:
    for issue in issues:
        console.rule(f"[bold red]Problema em {escape(issue.container)}")
        console.print(escape(issue.detail))
        agent.reset()  # cada problema é investigado do zero
        run_task(agent, issue.task())


def cmd_chat(agent: Agent) -> None:
    console.print("Converse com o agente. [bold]/limpar[/] zera a conversa, [bold]/sair[/] encerra.\n")
    while True:
        try:
            text = console.input("[bold green]você>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in ("/sair", "sair", "exit", "quit"):
            break
        if text.lower() == "/limpar":
            agent.reset()
            console.print("[dim]conversa zerada[/]")
            continue
        try:
            run_task(agent, text)
        except KeyboardInterrupt:
            console.print("[yellow]interrompido[/]")


def cmd_check(agent: Agent, monitor: Monitor) -> None:
    issues = monitor.scan()
    if not issues:
        console.print("[green]Nenhum problema encontrado.[/]")
        return
    console.print(f"[bold]{len(issues)} container(s) com problema.[/]")
    handle_issues(agent, issues)


def cmd_watch(agent: Agent, monitor: Monitor, interval: int) -> None:
    console.print(f"Monitorando a cada {interval}s. [bold]Ctrl+C[/] para parar.\n")
    while True:
        try:
            issues = monitor.due(monitor.scan())
        except dk.DockerError as e:
            console.print(f"[red]Erro ao consultar o Docker:[/] {escape(str(e))}")
            issues = []
        handle_issues(agent, issues)
        stamp = datetime.now().strftime("%H:%M:%S")
        with console.status(f"[dim]monitorando... última verificação às {stamp}[/]"):
            time.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="devops_agent", description="Agente de DevOps local (Ollama) para Docker.")
    p.add_argument("--model", help="modelo do Ollama (padrão: qwen3:4b ou AGENT_MODEL)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("chat", help="conversa interativa com o agente")
    ask = sub.add_parser("ask", help="faz uma pergunta e sai")
    ask.add_argument("question", nargs="+")

    for name, help_text in (("check", "verifica uma vez e diagnostica problemas"), ("watch", "monitora continuamente")):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--only", help="só estes containers (separados por vírgula)")
        s.add_argument("--scan-logs", action="store_true", help="também procura linhas de erro nos logs")
        if name == "watch":
            s.add_argument("--interval", type=int, default=30, help="segundos entre verificações (padrão 30)")
            s.add_argument("--cooldown", type=int, default=600, help="segundos antes de alertar de novo o mesmo container")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config()
    if args.model:
        cfg.model = args.model

    if not preflight(cfg):
        return 1

    agent = Agent(cfg, console, ask_approval, AuditLog(cfg.audit_file))
    try:
        if args.command == "chat":
            cmd_chat(agent)
        elif args.command == "ask":
            run_task(agent, " ".join(args.question))
        else:
            only = {n.strip() for n in args.only.split(",") if n.strip()} if args.only else None
            if args.command == "check":
                cmd_check(agent, Monitor(only=only, scan_logs=args.scan_logs, log_window=300))
            else:
                monitor = Monitor(only=only, scan_logs=args.scan_logs, log_window=args.interval, cooldown=args.cooldown)
                cmd_watch(agent, monitor, args.interval)
    except KeyboardInterrupt:
        console.print("\n[dim]encerrado[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
