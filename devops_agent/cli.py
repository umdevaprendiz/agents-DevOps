"""Command line: chat, ask, check and watch."""
from __future__ import annotations

import argparse
import time
from datetime import datetime

import ollama
from rich.markup import escape

from . import docker_tools as dk
from . import i18n
from .agent import Agent
from .audit import AuditLog
from .config import Config, load_env_file
from .i18n import t
from .monitor import Issue, Monitor
from .ui import ask_approval, console, show_answer, show_dim, show_error, show_ok, spinner
from .workers import Investigator

EXIT_COMMANDS = {"/exit", "/quit", "/sair", "exit", "quit", "sair"}
RESET_COMMANDS = {"/clear", "/limpar"}
CHECK_LOG_WINDOW = 300  # seconds of logs scanned by the check command


# --- Startup checks ---------------------------------------------------------------------------------

def preflight(cfg: Config) -> bool:
    docker_ok = _check_docker()
    ollama_ok = _check_ollama(cfg)
    return docker_ok and ollama_ok


def _check_docker() -> bool:
    try:
        show_ok(t("cli.docker_ok", version=dk.server_version()))
        return True
    except dk.DockerError as error:
        show_error(t("cli.docker_down"), str(error), t("cli.docker_hint"))
        return False


def _check_ollama(cfg: Config) -> bool:
    try:
        ollama.Client(host=cfg.ollama_host).show(cfg.model)
        show_ok(t("cli.ollama_ok", model=cfg.model))
        return True
    except ollama.ResponseError:
        show_error(t("cli.model_missing", model=cfg.model), hint=t("cli.model_hint", model=cfg.model))
    except Exception as error:  # connection refused, timeout...
        show_error(t("cli.ollama_down"), str(error), t("cli.ollama_hint"))
    return False


# --- Single agent: chat and ask ----------------------------------------------------------------------

def run_task(agent: Agent, task: str) -> None:
    try:
        show_answer(agent.run(task))
    except ollama.ResponseError as error:
        show_error(t("cli.ollama_error"), str(error))
    except (ConnectionError, OSError) as error:
        show_error(t("cli.ollama_unreachable"), str(error))


def cmd_chat(agent: Agent) -> None:
    console.print(t("cli.chat_intro"))
    while True:
        text = _read_input()
        if text is None or text.lower() in EXIT_COMMANDS:
            return
        _chat_turn(agent, text)


def _read_input() -> str | None:
    """Reads one line; None when the operator quits (Ctrl+C / Ctrl+D)."""
    try:
        return console.input(f"[bold green]{t('cli.prompt')}[/] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _chat_turn(agent: Agent, text: str) -> None:
    if not text:
        return
    if text.lower() in RESET_COMMANDS:
        agent.reset()
        show_dim(t("cli.chat_reset"))
        return
    try:
        run_task(agent, text)
    except KeyboardInterrupt:
        console.print(f"[yellow]{t('cli.interrupted')}[/]")


def cmd_ask(agent: Agent, question: str) -> None:
    run_task(agent, question)


# --- Incidents: check and watch ------------------------------------------------------------------------

def submit_issues(investigator: Investigator, issues: list[Issue]) -> int:
    """Queues the issues; returns how many were new (not already under investigation)."""
    submitted = 0
    for issue in issues:
        if investigator.submit(issue):
            _show_issue(issue)
            submitted += 1
    return submitted


def _show_issue(issue: Issue) -> None:
    console.rule(f"[bold red]{escape(t('cli.issue_header', container=issue.container))}")
    console.print(escape(issue.detail))


def report_result(issue: Issue, answer: str) -> None:
    show_answer(answer, label=issue.container)


def report_error(issue: Issue, error: Exception) -> None:
    show_error(t("cli.investigation_failed", container=escape(issue.container)), str(error))


def cmd_check(investigator: Investigator, monitor: Monitor) -> None:
    issues = monitor.scan()
    if not issues:
        console.print(f"[green]{t('cli.no_problems')}[/]")
        return
    console.print(f"[bold]{t('cli.problems_found', count=len(issues))}[/]")
    submit_issues(investigator, issues)
    investigator.wait()


def cmd_watch(investigator: Investigator, monitor: Monitor, interval: int) -> None:
    console.print(t("cli.watching", interval=interval, workers=investigator.size))
    last = None
    while True:
        submitted = submit_issues(investigator, monitor.due(_safe_scan(monitor)))
        last = _heartbeat(submitted, investigator.busy(), last)
        time.sleep(interval)


def _safe_scan(monitor: Monitor) -> list[Issue]:
    try:
        return monitor.scan()
    except dk.DockerError as error:
        show_error(t("cli.docker_query_error"), str(error))
        return []


def _heartbeat(new: int, running: int, last: tuple[int, int] | None) -> tuple[int, int]:
    """Prints a status line only when something changed, so idle watching stays quiet."""
    snapshot = (new, running)
    if snapshot != last:
        show_dim(t("cli.heartbeat", time=datetime.now().strftime("%H:%M:%S"), new=new, running=running))
    return snapshot


def build_investigator(cfg: Config, audit: AuditLog) -> Investigator:
    def investigate(issue: Issue) -> str:
        # One Agent per investigation: agents keep conversation state and are not thread-safe.
        agent = Agent(cfg, console, ask_approval, audit, label=issue.container)
        return agent.run(issue.task(), require_evidence=True)

    return Investigator(investigate, cfg.workers, on_result=report_result, on_error=report_error)


# --- Arguments -----------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devops-agent", description=t("cli.help.description"))
    parser.add_argument("--model", help=t("cli.help.model"))
    parser.add_argument("--lang", help=t("cli.help.lang"))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("chat", help=t("cli.help.chat"))
    sub.add_parser("ask", help=t("cli.help.ask")).add_argument("question", nargs="+")
    _add_monitor_options(sub.add_parser("check", help=t("cli.help.check")))
    _add_watch_options(sub.add_parser("watch", help=t("cli.help.watch")))
    return parser


def _add_monitor_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--only", help=t("cli.help.only"))
    parser.add_argument("--scan-logs", action="store_true", help=t("cli.help.scan_logs"))
    parser.add_argument("--workers", type=int, help=t("cli.help.workers"))


def _add_watch_options(parser: argparse.ArgumentParser) -> None:
    _add_monitor_options(parser)
    parser.add_argument("--interval", type=int, default=30, help=t("cli.help.interval"))
    parser.add_argument("--cooldown", type=int, default=600, help=t("cli.help.cooldown"))


def _language_argument(argv: list[str] | None) -> str | None:
    """Reads --lang before building the parser, so the help text is already translated."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang")
    known, _ = pre.parse_known_args(argv)
    return known.lang


def _parse_only(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {name.strip() for name in value.split(",") if name.strip()}


def _apply_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    if args.model:
        cfg.model = args.model
    if getattr(args, "workers", None):
        cfg.workers = args.workers
    return cfg


def _build_monitor(args: argparse.Namespace) -> Monitor:
    only = _parse_only(args.only)
    if args.command == "check":
        return Monitor(only=only, scan_logs=args.scan_logs, log_window=CHECK_LOG_WINDOW)
    return Monitor(only=only, scan_logs=args.scan_logs, log_window=args.interval, cooldown=args.cooldown)


def _dispatch(args: argparse.Namespace, cfg: Config, audit: AuditLog) -> None:
    if args.command == "chat":
        cmd_chat(Agent(cfg, console, ask_approval, audit, progress=spinner))
    elif args.command == "ask":
        cmd_ask(Agent(cfg, console, ask_approval, audit, progress=spinner), " ".join(args.question))
    elif args.command == "check":
        cmd_check(build_investigator(cfg, audit), _build_monitor(args))
    else:
        cmd_watch(build_investigator(cfg, audit), _build_monitor(args), args.interval)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    cfg = Config()
    cfg.language = i18n.set_language(_language_argument(argv) or cfg.language)
    args = build_parser().parse_args(argv)
    _apply_overrides(cfg, args)
    if not preflight(cfg):
        return 1
    try:
        _dispatch(args, cfg, AuditLog(cfg.audit_file))
    except KeyboardInterrupt:
        show_dim(t("cli.stopped"))
    return 0
