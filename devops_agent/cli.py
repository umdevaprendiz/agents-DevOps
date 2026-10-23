"""Command line: chat, ask, check and watch."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

import ollama
from rich.markup import escape
from rich.table import Table

from . import docker_tools as dk
from . import git_tools as git
from . import i18n
from . import security
from .agent import ANALYST, Agent
from .audit import AuditLog
from .commands import Session, ask_agent, debug, run_chat
from .config import Config, load_env_file
from .i18n import t
from .monitor import Issue, Monitor
from .pipeline import Team
from .proposals import ProposalStore
from .tools import Toolbox, build_toolbox
from .ui import ask_approval, console, show_answer, show_brief, show_dim, show_error, show_ok, spinner
from .workers import Investigator
from .workspace import Workspace

CHECK_LOG_WINDOW = 300  # seconds of logs scanned by the check command
SEVERITY_STYLES = {"high": "bold red", "medium": "yellow", "low": "dim"}


# --- Startup checks ---------------------------------------------------------------------------------

def preflight(cfg: Config) -> bool:
    checks = (_check_docker(), _check_ollama(cfg), _check_workspace(cfg))
    return all(checks)


def _check_docker() -> bool:
    try:
        show_ok(t("cli.docker_ok", version=dk.server_version()))
        return True
    except dk.DockerError as error:
        show_error(t("cli.docker_down"), str(error), t("cli.docker_hint"))
        return False


def _check_ollama(cfg: Config) -> bool:
    client = ollama.Client(host=cfg.ollama_host)
    return all([_check_model(client, model) for model in cfg.models()])


def _check_model(client: ollama.Client, model: str) -> bool:
    try:
        client.show(model)
        show_ok(t("cli.ollama_ok", model=model))
        return True
    except ollama.ResponseError:
        show_error(t("cli.model_missing", model=model), hint=t("cli.model_hint", model=model))
    except Exception as error:  # connection refused, timeout...
        show_error(t("cli.ollama_down"), str(error), t("cli.ollama_hint"))
    return False


def _check_workspace(cfg: Config) -> bool:
    root = cfg.workspace.resolve()
    if not root.is_dir():
        show_error(t("cli.workspace_missing"), str(root), t("cli.workspace_hint"))
        return False
    if git.is_repo(root):
        show_ok(t("cli.workspace_ok", path=escape(str(root)), branch=escape(git.current_branch(root))))
    else:
        show_dim(t("cli.workspace_no_git", path=str(root)))
    return True


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


def build_team(cfg: Config, audit: AuditLog, tools: Toolbox | None = None, label: str | None = None, progress=None) -> Team:
    """The heavy model resolves; with AGENT_FAST_MODEL set, a fast read-only model investigates first."""
    tools = tools or build_toolbox()
    resolver = Agent(cfg, console, ask_approval, audit, label=label, progress=progress, tools=tools)
    if not cfg.fast_model:
        return Team(resolver)
    analyst_label = f"{label} · {cfg.fast_model}" if label else cfg.fast_model
    analyst = Agent(
        cfg, console, ask_approval, audit, label=analyst_label, progress=progress,
        tools=tools.read_only(), model=cfg.fast_model, role=ANALYST,
    )
    return Team(resolver, analyst, on_brief=lambda brief: show_brief(brief, cfg.fast_model, label))


def build_investigator(cfg: Config, audit: AuditLog, tools: Toolbox | None = None) -> Investigator:
    def investigate(issue: Issue) -> str:
        # One team per investigation: agents keep conversation state and are not thread-safe.
        team = build_team(cfg, audit, tools, label=issue.container)
        return team.run(issue.task(), require_evidence=True)

    return Investigator(investigate, cfg.workers, on_result=report_result, on_error=report_error)


# --- Security audit (no model, no Ollama needed) ----------------------------------------------------------

def run_audit(cfg: Config, args: argparse.Namespace) -> int:
    """Exit code 0 = nothing at or above --fail-on, 1 = findings at or above it, 2 = no workspace."""
    if not cfg.workspace.resolve().is_dir():
        show_error(t("cli.workspace_missing"), str(cfg.workspace.resolve()), t("cli.workspace_hint"))
        return 2
    use_docker = not args.no_docker and security.docker_available()
    findings = security.audit(Workspace(cfg.workspace), docker=use_docker)
    if args.json:
        _write_utf8(security.as_json(findings) + "\n")
    else:
        show_findings(findings)
    return 1 if security.fails(findings, args.fail_on) else 0


def _write_utf8(text: str) -> None:
    """Machine output is always UTF-8, whatever the console code page (cp1252 on Windows)."""
    sys.stdout.flush()
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def show_findings(findings: list[security.Finding]) -> None:
    if not findings:
        show_ok(escape(t("sec.report.none")))
        return
    title = t("sec.report.header", **security.count_by_severity(findings))
    table = Table(title=escape(title), title_justify="left", show_lines=True)
    for key in ("sec.col.severity", "sec.col.rule", "sec.col.location", "sec.col.problem"):
        table.add_column(t(key))
    for finding in findings:
        table.add_row(*_finding_cells(finding))
    console.print(table)


def _finding_cells(finding: security.Finding) -> tuple[str, str, str, str]:
    style = SEVERITY_STYLES[finding.severity]
    problem = escape(finding.title())
    if finding.detail:
        problem += f"\n[dim]{escape(finding.detail)}[/]"
    problem += f"\n[cyan]→ {escape(finding.fix())}[/]"
    return f"[{style}]{security.severity_label(finding.severity)}[/]", finding.rule.id, escape(finding.location), problem


# --- Arguments -----------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devops-agent", description=t("cli.help.description"))
    parser.add_argument("--model", help=t("cli.help.model"))
    parser.add_argument("--fast-model", help=t("cli.help.fast_model"))
    parser.add_argument("--lang", help=t("cli.help.lang"))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("chat", help=t("cli.help.chat"))
    sub.add_parser("ask", help=t("cli.help.ask")).add_argument("question", nargs="+")
    sub.add_parser("debug", help=t("cli.help.debug")).add_argument("focus", nargs="*", help=t("cli.help.focus"))
    _add_audit_options(sub.add_parser("audit", help=t("cli.help.audit")))
    _add_monitor_options(sub.add_parser("check", help=t("cli.help.check")))
    _add_watch_options(sub.add_parser("watch", help=t("cli.help.watch")))
    return parser


def _add_audit_options(parser: argparse.ArgumentParser) -> None:
    choices = [*security.SEVERITIES, security.NEVER]
    parser.add_argument("--fail-on", choices=choices, default="high", help=t("cli.help.fail_on"))
    parser.add_argument("--json", action="store_true", help=t("cli.help.json"))
    parser.add_argument("--no-docker", action="store_true", help=t("cli.help.no_docker"))


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
    if args.fast_model:
        cfg.fast_model = args.fast_model
    if getattr(args, "workers", None):
        cfg.workers = args.workers
    return cfg


def _build_monitor(args: argparse.Namespace) -> Monitor:
    only = _parse_only(args.only)
    if args.command == "check":
        return Monitor(only=only, scan_logs=args.scan_logs, log_window=CHECK_LOG_WINDOW)
    return Monitor(only=only, scan_logs=args.scan_logs, log_window=args.interval, cooldown=args.cooldown)


def build_tools(cfg: Config) -> tuple[Toolbox, ProposalStore]:
    workspace = Workspace(cfg.workspace)
    proposals = ProposalStore(workspace)
    return build_toolbox(workspace, proposals), proposals


def _dispatch(args: argparse.Namespace, cfg: Config, audit: AuditLog) -> None:
    tools, proposals = build_tools(cfg)
    if args.command in ("check", "watch"):
        _run_monitor(args, cfg, audit, tools)
        return
    team = build_team(cfg, audit, tools, progress=spinner)
    if args.command == "chat":
        run_chat(Session(team.resolver, proposals, cfg, team=team))
    elif args.command == "debug":
        _run_debug(team, proposals, args.focus)
    else:
        ask_agent(team.resolver, " ".join(args.question))


def _run_monitor(args: argparse.Namespace, cfg: Config, audit: AuditLog, tools: Toolbox) -> None:
    investigator = build_investigator(cfg, audit, tools)
    if args.command == "check":
        cmd_check(investigator, _build_monitor(args))
    else:
        cmd_watch(investigator, _build_monitor(args), args.interval)


def _run_debug(team: Team, proposals: ProposalStore, focus_words: list[str]) -> None:
    if debug(team, proposals, " ".join(focus_words)):
        show_dim(t("cli.review_in_chat"))


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    cfg = Config()
    cfg.language = i18n.set_language(_language_argument(argv) or cfg.language)
    args = build_parser().parse_args(argv)
    _apply_overrides(cfg, args)
    if args.command == "audit":
        return run_audit(cfg, args)
    if not preflight(cfg):
        return 1
    try:
        _dispatch(args, cfg, AuditLog(cfg.audit_file))
    except KeyboardInterrupt:
        show_dim(t("cli.stopped"))
    return 0
