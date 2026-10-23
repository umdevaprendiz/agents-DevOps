import io

import pytest
from rich.console import Console

from devops_agent import commands, i18n, ui
from devops_agent.commands import COMMANDS, Session, dispatch, find, handle_input
from devops_agent.config import Config
from devops_agent.proposals import ProposalStore
from devops_agent.workspace import Workspace
from tests.conftest import COMPOSE, git, write

PORT_EDIT = {"path": "docker-compose.yml", "old_text": "localhost:8081", "new_text": "localhost:80"}


class FakeAgent:
    """Records tasks; can create a proposal while 'thinking', like the real agent would."""

    def __init__(self, store=None, propose=False):
        self.tasks = []
        self.resets = 0
        self._store = store
        self._propose = propose

    def run(self, task, require_evidence=False):
        self.tasks.append(task)
        if self._propose:
            self._store.create("Fix healthcheck port", "nginx listens on 80", [PORT_EDIT])
        return "agent answer"

    def reset(self):
        self.resets += 1


@pytest.fixture
def output(monkeypatch):
    """Captures everything printed by the commands and the ui helpers."""
    buffer = io.StringIO()
    console = Console(file=buffer, width=160)
    monkeypatch.setattr(ui, "console", console)
    monkeypatch.setattr(commands, "console", console)
    return buffer


@pytest.fixture
def answers(monkeypatch):
    """Scripted answers for every yes/no confirmation."""
    replies = []
    monkeypatch.setattr(commands, "confirm", lambda question: replies.pop(0))
    return replies


@pytest.fixture
def session(git_repo):
    store = ProposalStore(Workspace(git_repo))
    return Session(FakeAgent(store), store, Config())


def compose(session) -> str:
    return (session.proposals.workspace.root / "docker-compose.yml").read_text(encoding="utf-8")


# --- Routing ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "typed, name",
    [("/help", "/help"), ("/AJUDA", "/help"), ("/explicar", "/explain"), ("/sugerir", "/suggest"),
     ("/aplicar", "/apply"), ("/descartar", "/discard"), ("/desfazer", "/undo"), ("/sair", "/exit")],
)
def test_commands_have_english_names_and_portuguese_aliases(typed, name):
    assert find(typed).name == name


def test_unknown_command_points_to_help(session, output):
    dispatch(session, "/deploy-prod")
    assert "Unknown command: /deploy-prod" in output.getvalue()


def test_help_lists_every_command(session, output):
    dispatch(session, "/help")
    for command in COMMANDS:
        assert command.name in output.getvalue()


def test_plain_text_goes_to_the_agent(session, output):
    handle_input(session, "why is web unhealthy?")
    assert session.agent.tasks == ["why is web unhealthy?"]
    assert "agent answer" in output.getvalue()


@pytest.mark.parametrize("text", ["/exit", "/sair", "exit", "sair"])
def test_exit(session, text):
    handle_input(session, text)
    assert session.running is False


def test_clear_resets_the_conversation(session, output):
    dispatch(session, "/limpar")
    assert session.agent.resets == 1


def test_status_shows_model_and_branch(session, output):
    dispatch(session, "/status")
    assert session.cfg.model in output.getvalue() and "main" in output.getvalue()


# --- /debug --------------------------------------------------------------------------------------

def test_debug_investigates_everything_by_default(session, output):
    dispatch(session, "/debug")
    task = session.agent.tasks[0]
    assert "the whole environment" in task and "collect_diagnostics" in task


def test_debug_accepts_a_focus_and_a_portuguese_alias(session, output):
    i18n.set_language("pt-BR")
    dispatch(session, "/depurar demo-api")
    assert session.agent.tasks[0].startswith("Depure demo-api.")


def test_debug_announces_the_fixes_it_proposed(git_repo, output):
    store = ProposalStore(Workspace(git_repo))
    session = Session(FakeAgent(store, propose=True), store, Config())
    dispatch(session, "/debug web")
    assert f"/apply {store.get().id}" in output.getvalue()


# --- Two models ------------------------------------------------------------------------------------

def test_investigative_commands_use_the_team_and_chat_uses_the_main_model(git_repo, output):
    from devops_agent.pipeline import Team

    store = ProposalStore(Workspace(git_repo))
    chat_agent, analyst = FakeAgent(store), FakeAgent(store)
    session = Session(chat_agent, store, Config(), team=Team(chat_agent, analyst))

    handle_input(session, "hello")
    dispatch(session, "/debug web")

    assert len(analyst.tasks) == 1 and "Debug web" in analyst.tasks[0]
    assert chat_agent.tasks[0] == "hello"
    assert "A faster model already investigated" in chat_agent.tasks[1]


def test_clear_resets_both_models(git_repo, output):
    from devops_agent.pipeline import Team

    store = ProposalStore(Workspace(git_repo))
    chat_agent, analyst = FakeAgent(store), FakeAgent(store)
    session = Session(chat_agent, store, Config(), team=Team(chat_agent, analyst))
    dispatch(session, "/clear")
    assert (chat_agent.resets, analyst.resets) == (1, 1)


def test_status_shows_the_investigation_model(session, output):
    session.cfg.fast_model = "qwen3:1.7b"
    dispatch(session, "/status")
    assert "qwen3:1.7b" in output.getvalue()


# --- /audit --------------------------------------------------------------------------------------

def test_audit_asks_the_agent_to_run_the_security_audit(session, output):
    dispatch(session, "/audit secrets")
    task = session.agent.tasks[0]
    assert task.startswith("Run audit_security, then focus on: secrets")


def test_audit_has_a_portuguese_alias(session, output):
    i18n.set_language("pt-BR")
    dispatch(session, "/auditar")
    assert session.agent.tasks[0].startswith("Rode audit_security e aja")


# --- /suggest ------------------------------------------------------------------------------------

def test_suggest_sends_the_focus_and_announces_new_proposals(git_repo, output):
    store = ProposalStore(Workspace(git_repo))
    session = Session(FakeAgent(store, propose=True), store, Config())

    dispatch(session, "/suggest healthcheck")

    assert "focusing on: healthcheck" in session.agent.tasks[0]
    proposal = store.get()
    assert f"Proposal {proposal.id}" in output.getvalue()
    assert f"/apply {proposal.id}" in output.getvalue()


def test_suggest_without_changes(session, output):
    dispatch(session, "/suggest")
    assert "no change proposed" in output.getvalue()


def test_suggest_follows_the_language(git_repo, output):
    i18n.set_language("pt-BR")
    store = ProposalStore(Workspace(git_repo))
    session = Session(FakeAgent(store), store, Config())
    dispatch(session, "/sugerir segurança")
    assert "com foco em: segurança" in session.agent.tasks[0]


# --- Reviewing -----------------------------------------------------------------------------------

def test_proposals_diff_and_explain(session, output):
    proposal = session.proposals.create("Fix healthcheck port", "nginx listens on 80", [PORT_EDIT])

    dispatch(session, "/proposals")
    dispatch(session, f"/diff {proposal.id}")
    dispatch(session, "/explain")

    text = output.getvalue()
    assert proposal.id in text and "Fix healthcheck port" in text
    assert "localhost:80/" in text
    assert "localhost:80/" in session.agent.tasks[0] and "nginx listens on 80" in session.agent.tasks[0]


def test_explain_never_sends_secrets_from_the_diff_context(git_repo, output):
    secret = "hunter" + "2-" + "x" * 12
    write(git_repo, "app/config.yml", f"port: 3000\ndb_password={secret}\nlog_level: info\n")
    git(git_repo, "commit", "-q", "-am", "config")
    store = ProposalStore(Workspace(git_repo))
    session = Session(FakeAgent(store), store, Config())
    store.create("Debug logs", "why", [{"path": "app/config.yml", "old_text": "log_level: info", "new_text": "log_level: debug"}])

    dispatch(session, "/explain")

    assert secret not in session.agent.tasks[0]


def test_review_commands_without_proposals(session, output):
    dispatch(session, "/diff")
    assert "No pending proposals" in output.getvalue()


# --- Deciding ------------------------------------------------------------------------------------

def test_apply_only_after_confirmation(session, output, answers):
    proposal = session.proposals.create("Fix port", "why", [PORT_EDIT])

    answers.append(False)
    dispatch(session, "/apply")
    assert compose(session) == COMPOSE

    answers.append(True)
    dispatch(session, f"/aplicar {proposal.id}")
    assert "localhost:80/" in compose(session)
    assert "merged into main" in output.getvalue()


def test_undo_after_apply(session, output, answers):
    session.proposals.apply(session.proposals.create("Fix port", "why", [PORT_EDIT]))
    answers.append(True)
    dispatch(session, "/desfazer")
    assert compose(session) == COMPOSE


def test_discard(session, output, answers):
    session.proposals.create("Fix port", "why", [PORT_EDIT])
    answers.append(True)
    dispatch(session, "/discard")
    assert session.proposals.pending() == []


def test_pull_request_is_not_sent_without_confirmation(session, output, answers, monkeypatch):
    session.proposals.create("Fix port", "why", [PORT_EDIT])
    pushed = []
    monkeypatch.setattr(session.proposals, "open_pull_request", lambda proposal: pushed.append(proposal) or "url")
    answers.append(False)
    dispatch(session, "/pr")
    assert pushed == []


def test_command_errors_are_reported_not_raised(session, output, answers):
    answers.append(True)
    dispatch(session, "/undo")
    assert "Could not complete the command" in output.getvalue()
