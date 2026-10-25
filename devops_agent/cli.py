"""Command line: chat, ask, debug, audit, eval, check and watch."""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime
from typing import Iterator

import ollama
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import docker_tools as dk
from . import evaluation
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


def build_team(
    cfg: Config,
    audit: AuditLog,
    tools: Toolbox | None = None,
    label: str | None = None,
    progress=None,
    approver=None,
    out: Console | None = None,
    on_brief=None,
) -> Team:
    """The heavy model resolves; with AGENT_FAST_MODEL set, a fast read-only model investigates first.
    The evaluation passes its own approver, output and report handler."""
    tools = tools or build_toolbox()
    approver, out = approver or ask_approval, out or console
    resolver = Agent(cfg, out, approver, audit, label=label, progress=progress, tools=tools)
    if not cfg.fast_model:
        return Team(resolver)
    analyst_label = f"{label} · {cfg.fast_model}" if label else cfg.fast_model
    analyst = Agent(
        cfg, out, approver, audit, label=analyst_label, progress=progress,
        tools=tools.read_only(), model=cfg.fast_model, role=ANALYST,
    )
    on_brief = on_brief or (lambda brief: show_brief(brief, cfg.fast_model, label))
    return Team(resolver, analyst, on_brief=on_brief)


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


# --- Model evaluation (simulated scenarios: no Docker, no project needed) --------------------------------

def run_eval(cfg: Config, args: argparse.Namespace) -> int:
    """Exit code 0 = done, 1 = setup failed or the pass rate is below --fail-under, 2 = invalid scenarios."""
    with _human_output(to_stderr=args.json):
        try:
            scenarios = evaluation.select(evaluation.load_scenarios(args.scenarios_dir), args.scenario)
        except evaluation.ScenarioError as error:
            show_error(t("eval.invalid"), str(error))
            return 2
        if args.list:
            evaluation.show_scenarios(console, scenarios)
            return 0
        if not _check_git():
            return 1
        if args.validate:
            return _run_validation(scenarios)
        if not _check_ollama(cfg):
            return 1
        return _run_models(cfg, args, scenarios)


def _run_models(cfg: Config, args: argparse.Namespace, scenarios: list[evaluation.Scenario]) -> int:
    repeat = max(1, args.repeat)
    results = evaluation.evaluate(
        scenarios,
        eval_team_factory(cfg, args.verbose),
        repeat,
        progress=_eval_progress(len(scenarios), repeat),
        on_result=lambda result: evaluation.show_run(console, result),
    )
    if args.json:
        models = {"resolver": cfg.model, "analyst": cfg.fast_model}
        _write_utf8(evaluation.as_json(results, models, cfg.language, repeat) + "\n")
    else:
        evaluation.show_results(console, results, evaluation.models_label(cfg.model, cfg.fast_model), repeat)
    return _threshold_exit(results, args.fail_under)


def eval_team_factory(cfg: Config, verbose: bool) -> evaluation.TeamFactory:
    """The same agents as /debug, but container actions are refused and nothing is printed unless --verbose."""
    out = console if verbose else Console(quiet=True)

    def make(scenario, tools, events, on_brief) -> Team:
        def brief(text: str) -> None:
            on_brief(text)
            if verbose:
                show_brief(text, cfg.fast_model, scenario.id)

        label = scenario.id if verbose else None
        return build_team(cfg, events, tools, label=label, approver=evaluation.deny_actions, out=out, on_brief=brief)

    return make


def _eval_progress(total: int, repeat: int):
    order: dict[str, int] = {}

    def progress(scenario: evaluation.Scenario, attempt: int):
        index = order.setdefault(scenario.id, len(order) + 1)
        label = evaluation.run_label(scenario, attempt, repeat, index, total)
        if console.is_terminal:
            return spinner(label)
        # Output redirected to a file: a spinner draws nothing there, so each run gets a plain line.
        show_dim(label)
        return nullcontext()

    return progress


def _threshold_exit(results: list[evaluation.RunResult], fail_under: float | None) -> int:
    if fail_under is None:
        return 0
    rate = evaluation.summarize("total", results).passed.percent
    if rate < fail_under:
        show_error(t("eval.below_threshold", rate=rate, threshold=fail_under))
        return 1
    return 0


def _run_validation(scenarios: list[evaluation.Scenario]) -> int:
    with spinner(t("eval.validating")):
        validations = evaluation.validate(scenarios)
    evaluation.show_validation(console, validations)
    return 0 if all(item.ok for item in validations) else 1


def _check_git() -> bool:
    if shutil.which("git"):
        return True
    show_error(t("eval.git_missing"))
    return False


@contextmanager
def _human_output(to_stderr: bool) -> Iterator[None]:
    """With --json, terminal messages go to stderr so stdout carries only the JSON."""
    if not to_stderr:
        yield
        return
    previous, console.file = console.file, sys.stderr
    try:
        yield
    finally:
        console.file = previous


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
    _add_eval_options(sub.add_parser("eval", help=t("cli.help.eval")))
    _add_monitor_options(sub.add_parser("check", help=t("cli.help.check")))
    _add_watch_options(sub.add_parser("watch", help=t("cli.help.watch")))
    return parser


def _add_audit_options(parser: argparse.ArgumentParser) -> None:
    choices = [*security.SEVERITIES, security.NEVER]
    parser.add_argument("--fail-on", choices=choices, default="high", help=t("cli.help.fail_on"))
    parser.add_argument("--json", action="store_true", help=t("cli.help.json"))
    parser.add_argument("--no-docker", action="store_true", help=t("cli.help.no_docker"))


def _add_eval_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scenario", action="append", metavar="ID", help=t("cli.help.scenario"))
    parser.add_argument("--scenarios-dir", metavar="DIR", help=t("cli.help.scenarios_dir"))
    parser.add_argument("--repeat", type=int, default=1, help=t("cli.help.repeat"))
    parser.add_argument("--fail-under", type=float, metavar="PCT", help=t("cli.help.fail_under_rate"))
    parser.add_argument("--json", action="store_true", help=t("cli.help.eval_json"))
    parser.add_argument("--verbose", action="store_true", help=t("cli.help.verbose"))
    parser.add_argument("--list", action="store_true", help=t("cli.help.list"))
    parser.add_argument("--validate", action="store_true", help=t("cli.help.validate"))


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


def _interruptible(command, cfg: Config, args: argparse.Namespace) -> int:
    """Ctrl+C stops the command cleanly (temporary folders are removed by their context managers)."""
    try:
        return command(cfg, args)
    except KeyboardInterrupt:
        show_dim(t("cli.stopped"))
        return 130


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    cfg = Config()
    cfg.language = i18n.set_language(_language_argument(argv) or cfg.language)
    args = build_parser().parse_args(argv)
    _apply_overrides(cfg, args)
    if args.command == "audit":
        return run_audit(cfg, args)
    if args.command == "eval":
        return _interruptible(run_eval, cfg, args)
    if not preflight(cfg):
        return 1
    try:
        _dispatch(args, cfg, AuditLog(cfg.audit_file))
    except KeyboardInterrupt:
        show_dim(t("cli.stopped"))
    return 0
