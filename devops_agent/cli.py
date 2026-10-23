"""Linha de comando: chat, ask, check e watch."""
from __future__ import annotations

import argparse
import time
from datetime import datetime

import ollama
from rich.markup import escape

from . import docker_tools as dk
from .agent import Agent
from .audit import AuditLog
from .config import Config
from .monitor import Issue, Monitor
from .ui import ask_approval, console, show_answer, show_dim, show_error, show_ok

EXIT_COMMANDS = {"/sair", "sair", "exit", "quit"}
RESET_COMMAND = "/limpar"
CHECK_LOG_WINDOW = 300  # segundos de log analisados pelo comando check


# --- verificação inicial ----------------------------------------------------------

def preflight(cfg: Config) -> bool:
    docker_ok = _check_docker()
    ollama_ok = _check_ollama(cfg)
    return docker_ok and ollama_ok


def _check_docker() -> bool:
    try:
        show_ok(f"Docker {dk.server_version()}")
        return True
    except dk.DockerError as error:
        show_error("✗ Docker indisponível:", str(error), "Abra o Docker Desktop e tente de novo.")
        return False


def _check_ollama(cfg: Config) -> bool:
    try:
        ollama.Client(host=cfg.ollama_host).show(cfg.model)
        show_ok(f"Ollama com o modelo {cfg.model}")
        return True
    except ollama.ResponseError:
        show_error(f"✗ Modelo '{cfg.model}' não encontrado.", hint=f"Rode: [bold]ollama pull {cfg.model}[/]")
    except Exception as error:  # conexão recusada, timeout...
        show_error("✗ Ollama não respondeu:", str(error), "Abra o Ollama e tente de novo.")
    return False


# --- execução de tarefas ----------------------------------------------------------

def run_task(agent: Agent, task: str, require_evidence: bool = False) -> None:
    try:
        show_answer(agent.run(task, require_evidence))
    except ollama.ResponseError as error:
        show_error("Erro do Ollama:", str(error))
    except (ConnectionError, OSError) as error:
        show_error("Não consegui falar com o Ollama:", str(error))


def handle_issues(agent: Agent, issues: list[Issue]) -> None:
    for issue in issues:
        _show_issue(issue)
        agent.reset()  # cada problema é investigado do zero
        run_task(agent, issue.task(), require_evidence=True)


def _show_issue(issue: Issue) -> None:
    console.rule(f"[bold red]Problema em {escape(issue.container)}")
    console.print(escape(issue.detail))


# --- comandos -----------------------------------------------------------------------

def cmd_chat(agent: Agent) -> None:
    console.print(f"Converse com o agente. [bold]{RESET_COMMAND}[/] zera a conversa, [bold]/sair[/] encerra.\n")
    while True:
        text = _read_input()
        if text is None or text.lower() in EXIT_COMMANDS:
            return
        _chat_turn(agent, text)


def _read_input() -> str | None:
    """Lê uma linha do usuário; None quando ele encerra (Ctrl+C / Ctrl+Z)."""
    try:
        return console.input("[bold green]você>[/] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _chat_turn(agent: Agent, text: str) -> None:
    if not text:
        return
    if text.lower() == RESET_COMMAND:
        agent.reset()
        show_dim("conversa zerada")
        return
    try:
        run_task(agent, text)
    except KeyboardInterrupt:
        console.print("[yellow]interrompido[/]")


def cmd_ask(agent: Agent, question: str) -> None:
    run_task(agent, question)


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
        handle_issues(agent, monitor.due(_safe_scan(monitor)))
        _wait(interval)


def _safe_scan(monitor: Monitor) -> list[Issue]:
    try:
        return monitor.scan()
    except dk.DockerError as error:
        show_error("Erro ao consultar o Docker:", str(error))
        return []


def _wait(seconds: int) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    with console.status(f"[dim]monitorando... última verificação às {stamp}[/]"):
        time.sleep(seconds)


# --- argumentos -----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devops_agent", description="Agente de DevOps local (Ollama) para Docker.")
    parser.add_argument("--model", help="modelo do Ollama (padrão: qwen3:4b ou AGENT_MODEL)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("chat", help="conversa interativa com o agente")
    sub.add_parser("ask", help="faz uma pergunta e sai").add_argument("question", nargs="+")
    _add_monitor_options(sub.add_parser("check", help="verifica uma vez e diagnostica problemas"))
    _add_watch_options(sub.add_parser("watch", help="monitora continuamente"))
    return parser


def _add_monitor_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--only", help="só estes containers (separados por vírgula)")
    parser.add_argument("--scan-logs", action="store_true", help="também procura linhas de erro nos logs")


def _add_watch_options(parser: argparse.ArgumentParser) -> None:
    _add_monitor_options(parser)
    parser.add_argument("--interval", type=int, default=30, help="segundos entre verificações (padrão 30)")
    parser.add_argument("--cooldown", type=int, default=600, help="segundos antes de alertar de novo o mesmo container")


def _parse_only(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {name.strip() for name in value.split(",") if name.strip()}


def _build_config(args: argparse.Namespace) -> Config:
    cfg = Config()
    if args.model:
        cfg.model = args.model
    return cfg


def _build_monitor(args: argparse.Namespace) -> Monitor:
    only = _parse_only(args.only)
    if args.command == "check":
        return Monitor(only=only, scan_logs=args.scan_logs, log_window=CHECK_LOG_WINDOW)
    return Monitor(only=only, scan_logs=args.scan_logs, log_window=args.interval, cooldown=args.cooldown)


def _dispatch(args: argparse.Namespace, agent: Agent) -> None:
    if args.command == "chat":
        cmd_chat(agent)
    elif args.command == "ask":
        cmd_ask(agent, " ".join(args.question))
    elif args.command == "check":
        cmd_check(agent, _build_monitor(args))
    else:
        cmd_watch(agent, _build_monitor(args), args.interval)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = _build_config(args)
    if not preflight(cfg):
        return 1
    agent = Agent(cfg, console, ask_approval, AuditLog(cfg.audit_file))
    try:
        _dispatch(args, agent)
    except KeyboardInterrupt:
        show_dim("\nencerrado")
    return 0
