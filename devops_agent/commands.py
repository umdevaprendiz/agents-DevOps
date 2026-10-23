"""Chat and its slash commands (/help, /suggest, /diff, /explain, /apply, /pr...).

The agent proposes, the operator reviews and decides. Every command has an English
name and a Portuguese alias.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import ollama
from rich.markup import escape

from . import git_tools as git
from .agent import Agent
from .config import Config
from .i18n import get_language, t
from .proposals import ProposalError, ProposalStore
from .redaction import redact
from .ui import confirm, console, show_answer, show_diff, show_dim, show_error, show_ok, show_table

EXIT_WORDS = {"exit", "quit", "sair"}
MAX_EXPLAIN_DIFF = 12_000


@dataclass
class Session:
    agent: Agent
    proposals: ProposalStore
    cfg: Config
    running: bool = True


Handler = Callable[[Session, str], None]


@dataclass(frozen=True)
class Command:
    name: str
    aliases: tuple[str, ...]
    usage: str
    help_key: str
    handler: Handler


# --- Talking to the agent ---------------------------------------------------------------------------

def ask_agent(agent: Agent, task: str) -> None:
    try:
        show_answer(agent.run(task))
    except ollama.ResponseError as error:
        show_error(t("cli.ollama_error"), str(error))
    except (ConnectionError, OSError) as error:
        show_error(t("cli.ollama_unreachable"), str(error))


# --- Chat loop ----------------------------------------------------------------------------------------

def run_chat(session: Session) -> None:
    console.print(t("cli.chat_intro"))
    while session.running:
        text = _read_input()
        if text is None:
            return
        handle_input(session, text)


def _read_input() -> str | None:
    """Reads one line; None when the operator quits (Ctrl+C / Ctrl+D)."""
    try:
        return console.input(f"[bold green]{t('cli.prompt')}[/] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None


def handle_input(session: Session, text: str) -> None:
    if not text:
        return
    if text.lower() in EXIT_WORDS:
        session.running = False
    elif text.startswith("/"):
        dispatch(session, text)
    else:
        _ask_interruptible(session, text)


def _ask_interruptible(session: Session, text: str) -> None:
    try:
        ask_agent(session.agent, text)
    except KeyboardInterrupt:
        console.print(f"[yellow]{t('cli.interrupted')}[/]")


def dispatch(session: Session, text: str) -> None:
    name, _, argument = text.partition(" ")
    command = find(name)
    if command is None:
        show_error(t("cmd.unknown", name=escape(name)))
        return
    try:
        command.handler(session, argument.strip())
    except (ProposalError, git.GitError) as error:
        show_error(t("cmd.failed"), str(error))


def find(name: str) -> Command | None:
    return _INDEX.get(name.lower())


# --- General commands ----------------------------------------------------------------------------------

def _help(session: Session, argument: str) -> None:
    rows = [(f"{c.name} {c.usage}".strip(), ", ".join(c.aliases), t(c.help_key)) for c in COMMANDS]
    show_table(t("cmd.help_title"), [t("cmd.col.command"), t("cmd.col.aliases"), t("cmd.col.description")], rows)


def _clear(session: Session, argument: str) -> None:
    session.agent.reset()
    show_dim(t("cli.chat_reset"))


def _exit(session: Session, argument: str) -> None:
    session.running = False


def _status(session: Session, argument: str) -> None:
    rows = [
        (t("cmd.status.model"), session.cfg.model),
        (t("cmd.status.language"), get_language()),
        (t("cmd.status.workspace"), str(session.proposals.workspace.root)),
        *_repository_rows(session),
    ]
    show_table(t("cmd.status_title"), ["", ""], rows)


def _repository_rows(session: Session) -> list[tuple[str, str]]:
    try:
        branch = session.proposals.current_branch()
        pending = len(session.proposals.pending())
    except (ProposalError, git.GitError):
        return [(t("cmd.status.branch"), t("cmd.not_a_repo"))]
    return [(t("cmd.status.branch"), branch), (t("cmd.status.proposals"), str(pending))]


# --- Debugging and suggestions (also used by the CLI) ---------------------------------------------------

def debug(agent: Agent, store: ProposalStore, focus: str = "") -> bool:
    """Full debugging session: find what fails, explain it and propose fixes.
    Returns True when new proposals were created."""
    target = focus or t("prompt.debug_everything")
    return _run_with_proposals(agent, store, t("prompt.debug", target=target))


def suggest(agent: Agent, store: ProposalStore, focus: str = "") -> bool:
    """Review the project and propose only the changes that are really necessary."""
    extra = t("prompt.suggest_focus", focus=focus) if focus else ""
    return _run_with_proposals(agent, store, t("prompt.suggest", focus=extra))


def _run_with_proposals(agent: Agent, store: ProposalStore, task: str) -> bool:
    before = {proposal.id for proposal in _safe_pending(store)}
    ask_agent(agent, task)
    return _announce_new(store, before)


def _announce_new(store: ProposalStore, before: set[str]) -> bool:
    new = [proposal for proposal in _safe_pending(store) if proposal.id not in before]
    if not new:
        show_dim(t("cmd.no_new_proposals"))
    for proposal in new:
        console.print(t("cmd.proposal_ready", id=proposal.id, title=escape(proposal.title)))
    return bool(new)


def _safe_pending(store: ProposalStore) -> list:
    try:
        return store.pending()
    except (ProposalError, git.GitError):
        return []


def _debug(session: Session, focus: str) -> None:
    debug(session.agent, session.proposals, focus)


def _suggest(session: Session, focus: str) -> None:
    suggest(session.agent, session.proposals, focus)


# --- Proposals -----------------------------------------------------------------------------------------


def _list(session: Session, argument: str) -> None:
    proposals = session.proposals.pending()
    if not proposals:
        show_dim(t("proposal.none"))
        return
    columns = [t("cmd.col.id"), t("cmd.col.title"), t("cmd.col.branch")]
    show_table(t("cmd.proposals_title"), columns, [(p.id, p.title, p.branch) for p in proposals])


def _diff(session: Session, ref: str) -> None:
    proposal = session.proposals.get(ref or None)
    show_diff(f"{proposal.id} · {proposal.title}", session.proposals.diff(proposal))


def _explain(session: Session, ref: str) -> None:
    proposal = session.proposals.get(ref or None)
    diff = redact(session.proposals.diff(proposal))[:MAX_EXPLAIN_DIFF]
    task = t("prompt.explain", title=proposal.title, explanation=proposal.explanation or "-", diff=diff)
    ask_agent(session.agent, task)


def _apply(session: Session, ref: str) -> None:
    proposal = session.proposals.get(ref or None)
    branch = session.proposals.current_branch()
    if confirm(t("cmd.confirm_apply", id=proposal.id, branch=escape(branch))):
        session.proposals.apply(proposal)
        show_ok(t("cmd.applied", id=proposal.id, branch=escape(branch)))


def _pull_request(session: Session, ref: str) -> None:
    proposal = session.proposals.get(ref or None)
    if confirm(t("cmd.confirm_pr", branch=escape(proposal.branch))):
        show_ok(escape(session.proposals.open_pull_request(proposal)))


def _discard(session: Session, ref: str) -> None:
    proposal = session.proposals.get(ref or None)
    if confirm(t("cmd.confirm_discard", id=proposal.id)):
        session.proposals.discard(proposal)
        show_ok(t("cmd.discarded", id=proposal.id))


def _undo(session: Session, argument: str) -> None:
    if confirm(t("cmd.confirm_undo")):
        show_ok(t("cmd.undone", commit=session.proposals.undo_last()))


COMMANDS: list[Command] = [
    Command("/help", ("/ajuda",), "", "cmd.help.help", _help),
    Command("/debug", ("/depurar",), "[focus]", "cmd.help.debug", _debug),
    Command("/suggest", ("/sugerir",), "[focus]", "cmd.help.suggest", _suggest),
    Command("/proposals", ("/propostas",), "", "cmd.help.proposals", _list),
    Command("/diff", (), "[id]", "cmd.help.diff", _diff),
    Command("/explain", ("/explicar",), "[id]", "cmd.help.explain", _explain),
    Command("/apply", ("/aplicar",), "[id]", "cmd.help.apply", _apply),
    Command("/pr", (), "[id]", "cmd.help.pr", _pull_request),
    Command("/discard", ("/descartar",), "[id]", "cmd.help.discard", _discard),
    Command("/undo", ("/desfazer",), "", "cmd.help.undo", _undo),
    Command("/status", (), "", "cmd.help.status", _status),
    Command("/clear", ("/limpar",), "", "cmd.help.clear", _clear),
    Command("/exit", ("/sair", "/quit"), "", "cmd.help.exit", _exit),
]

_INDEX = {alias: command for command in COMMANDS for alias in (command.name, *command.aliases)}
