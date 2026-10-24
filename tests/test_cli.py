import io
import json
import shutil
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from rich.console import Console
from rich.prompt import InvalidResponse

from devops_agent import cli, i18n, ui
from devops_agent.config import Config
from devops_agent.evaluation import EventLog, deny_actions
from devops_agent.evaluation.runner import ReferenceTeam, SilentTeam
from devops_agent.monitor import Issue
from devops_agent.proposals import ProposalStore
from devops_agent.tools import build_toolbox
from devops_agent.ui import YesNoConfirm
from devops_agent.workspace import Workspace


@pytest.fixture
def output(monkeypatch):
    """Captures what the CLI writes to the terminal."""
    buffer = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, width=120))
    return buffer


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch):
    """main() must not read a developer's local .env during tests."""
    monkeypatch.setattr(cli, "load_env_file", lambda: False)


class FakeAgent:
    def __init__(self):
        self.resets = 0
        self.runs = []

    def reset(self):
        self.resets += 1

    def run(self, task, require_evidence=False):
        self.runs.append((task, require_evidence))
        return f"answer {len(self.runs)}"


class FakeInvestigator:
    size = 3

    def __init__(self, busy_containers=()):
        self.submitted = []
        self.waited = False
        self._busy = set(busy_containers)

    def submit(self, issue):
        if issue.container in self._busy:
            return False
        self._busy.add(issue.container)
        self.submitted.append(issue)
        return True

    def busy(self):
        return len(self._busy)

    def wait(self):
        self.waited = True


# --- Arguments ---------------------------------------------------------------------------------------

def test_parse_only_splits_and_trims_names():
    assert cli._parse_only(" api, web ,,db ") == {"api", "web", "db"}
    assert cli._parse_only(None) is None


def test_watch_defaults():
    args = cli.build_parser().parse_args(["watch"])
    assert (args.interval, args.cooldown, args.scan_logs, args.only, args.workers) == (30, 600, False, None, None)


def test_overrides_from_arguments():
    args = cli.build_parser().parse_args(["--model", "qwen3:8b", "check", "--workers", "6"])
    cfg = cli._apply_overrides(Config(), args)
    assert (cfg.model, cfg.workers) == ("qwen3:8b", 6)


def test_command_is_required():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_check_monitor_uses_wider_log_window():
    args = cli.build_parser().parse_args(["check", "--only", "api", "--scan-logs"])
    monitor = cli._build_monitor(args)
    assert (monitor.only, monitor.scan_logs, monitor.log_window) == ({"api"}, True, cli.CHECK_LOG_WINDOW)


def test_watch_monitor_uses_interval_and_cooldown():
    args = cli.build_parser().parse_args(["watch", "--interval", "15", "--cooldown", "90"])
    monitor = cli._build_monitor(args)
    assert (monitor.log_window, monitor.cooldown) == (15, 90)


def test_debug_command_takes_an_optional_focus():
    assert cli.build_parser().parse_args(["debug"]).focus == []
    assert cli.build_parser().parse_args(["debug", "demo-api", "timeout"]).focus == ["demo-api", "timeout"]


def test_debug_points_to_the_chat_when_fixes_were_proposed(monkeypatch):
    calls, hints = [], []
    monkeypatch.setattr(cli, "debug", lambda agent, store, focus: calls.append(focus) or True)
    monkeypatch.setattr(cli, "show_dim", hints.append)
    cli._run_debug("agent", "store", ["demo-api", "timeout"])
    assert calls == ["demo-api timeout"]
    assert "/diff" in hints[0]


def test_language_argument_is_read_before_parsing():
    assert cli._language_argument(["--lang", "pt-BR", "check"]) == "pt-BR"
    assert cli._language_argument(["check"]) is None


# --- main ------------------------------------------------------------------------------------------

def test_main_stops_when_preflight_fails(monkeypatch):
    monkeypatch.setattr(cli, "preflight", lambda cfg: False)
    assert cli.main(["check"]) == 1


def test_main_applies_the_language_flag(monkeypatch):
    monkeypatch.setattr(cli, "preflight", lambda cfg: False)
    cli.main(["--lang", "pt-BR", "check"])
    assert i18n.get_language() == "pt-BR"


# --- Incidents ---------------------------------------------------------------------------------------

def test_check_without_issues(output):
    cli.cmd_check(FakeInvestigator(), SimpleNamespace(scan=lambda: []))
    assert "No problems found." in output.getvalue()


def test_check_submits_every_issue_and_waits(output):
    investigator = FakeInvestigator()
    issues = [Issue("api", ("x",)), Issue("web", ("y",))]
    cli.cmd_check(investigator, SimpleNamespace(scan=lambda: issues))
    assert investigator.submitted == issues
    assert investigator.waited


def test_issues_already_under_investigation_are_not_announced_again(output):
    investigator = FakeInvestigator(busy_containers={"api"})
    submitted = cli.submit_issues(investigator, [Issue("api", ("x",)), Issue("web", ("y",))])
    assert submitted == 1
    assert "Problem in web" in output.getvalue()
    assert "Problem in api" not in output.getvalue()


def test_results_are_shown_with_the_container_label(monkeypatch):
    shown = []
    monkeypatch.setattr(cli, "show_answer", lambda answer, label=None: shown.append((answer, label)))
    cli.report_result(Issue("api", ("x",)), "fixed")
    assert shown == [("fixed", "api")]


def test_heartbeat_prints_only_when_something_changes(monkeypatch):
    printed = []
    monkeypatch.setattr(cli, "show_dim", printed.append)
    last = cli._heartbeat(0, 0, None)
    last = cli._heartbeat(0, 0, last)
    cli._heartbeat(1, 1, last)
    assert len(printed) == 2


def test_investigator_runs_one_agent_per_issue_with_evidence(monkeypatch):
    created = []

    class RecordingAgent(FakeAgent):
        def __init__(self, cfg, console, approver, audit, label=None, progress=None, tools=None, model=None, role=None):
            super().__init__()
            self.label = label
            created.append(self)

    results = []
    monkeypatch.setattr(cli, "Agent", RecordingAgent)
    monkeypatch.setattr(cli, "report_result", lambda issue, answer: results.append((issue.container, answer)))
    cfg = Config()
    cfg.workers = 2
    investigator = cli.build_investigator(cfg, SimpleNamespace(log=lambda *a, **k: None))

    for name in ("api", "web"):
        investigator.submit(Issue(name, ("x",)))
    investigator.wait()

    assert sorted(agent.label for agent in created) == ["api", "web"]
    assert all(agent.runs[0][1] is True for agent in created)
    assert sorted(results) == [("api", "answer 1"), ("web", "answer 1")]


# --- Two models ----------------------------------------------------------------------------------------

def test_fast_model_option():
    args = cli.build_parser().parse_args(["--fast-model", "qwen3:1.7b", "debug"])
    assert cli._apply_overrides(Config(), args).fast_model == "qwen3:1.7b"


def test_single_model_team(tmp_path):
    cfg = Config()
    cfg.fast_model = None
    team = cli.build_team(cfg, SimpleNamespace(log=lambda *a, **k: None))
    assert team.two_stage is False
    assert team.resolver.model == cfg.model


def test_two_model_team_gives_the_analyst_only_read_tools(tmp_path):
    from devops_agent.proposals import ProposalStore
    from devops_agent.tools import build_toolbox
    from devops_agent.workspace import Workspace

    cfg = Config()
    cfg.model, cfg.fast_model = "qwen3:8b", "qwen3:4b"
    workspace = Workspace(tmp_path)
    tools = build_toolbox(workspace, ProposalStore(workspace))
    team = cli.build_team(cfg, SimpleNamespace(log=lambda *a, **k: None), tools, label="api")

    assert (team.resolver.model, team.analyst.model) == ("qwen3:8b", "qwen3:4b")
    assert team.analyst.role == "analyst" and team.analyst.label == "api · qwen3:4b"
    assert "propose_change" in team.resolver.tools.names()
    assert "propose_change" not in team.analyst.tools.names()
    assert "restart_container" not in team.analyst.tools.names()


def test_preflight_checks_every_model(monkeypatch, output):
    checked = []

    class FakeOllama:
        def __init__(self, host=None):
            pass

        def show(self, model):
            checked.append(model)

    monkeypatch.setattr(cli.ollama, "Client", FakeOllama)
    cfg = Config()
    cfg.model, cfg.fast_model = "qwen3:8b", "qwen3:4b"
    assert cli._check_ollama(cfg) is True
    assert checked == ["qwen3:8b", "qwen3:4b"]


# --- Workspace check -----------------------------------------------------------------------------------

def test_workspace_check_fails_for_a_missing_folder(output, tmp_path):
    cfg = Config()
    cfg.workspace = tmp_path / "missing"
    assert cli._check_workspace(cfg) is False


def test_workspace_check_accepts_folders_without_git(output, tmp_path):
    cfg = Config()
    cfg.workspace = tmp_path
    assert cli._check_workspace(cfg) is True


def test_workspace_check_shows_the_branch(monkeypatch, git_repo):
    shown = []
    monkeypatch.setattr(cli, "show_ok", shown.append)
    cfg = Config()
    cfg.workspace = git_repo
    assert cli._check_workspace(cfg) is True
    assert "branch main" in shown[0]


# --- Confirmation --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected", [("y", True), ("YES", True), ("s", True), ("sim", True), ("n", False), ("não", False)]
)
def test_yes_no_confirm_accepts_english_and_portuguese(value, expected):
    assert YesNoConfirm("Allow?").process_response(value) is expected


def test_yes_no_confirm_shows_choices_in_the_current_language():
    assert YesNoConfirm("Allow?").choices == ["y", "n"]
    i18n.set_language("pt-BR")
    assert YesNoConfirm("Permitir?").choices == ["s", "n"]


def test_yes_no_confirm_rejects_other_answers():
    with pytest.raises(InvalidResponse):
        YesNoConfirm("Allow?").process_response("maybe")


# --- Evaluation ----------------------------------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture
def eval_output(monkeypatch):
    """Captures the CLI output and the ui helpers (show_error, show_ok) in one buffer."""
    buffer = io.StringIO()
    console = Console(file=buffer, width=160)
    monkeypatch.setattr(cli, "console", console)
    monkeypatch.setattr(ui, "console", console)
    return buffer


@pytest.fixture
def eval_with(monkeypatch):
    """Runs `eval` with a stand-in team instead of a model (no Ollama, no spinner)."""
    monkeypatch.setattr(cli, "_check_ollama", lambda cfg: True)
    monkeypatch.setattr(cli, "spinner", lambda message: nullcontext())

    def install(make_team):
        monkeypatch.setattr(cli, "eval_team_factory", lambda cfg, verbose: make_team)

    return install


def reference_team(scenario, tools, events, on_brief):
    return ReferenceTeam(scenario, tools)


def silent_team(scenario, tools, events, on_brief):
    return SilentTeam()


def test_eval_options():
    args = cli.build_parser().parse_args(["eval"])
    assert (args.scenario, args.scenarios_dir, args.repeat, args.fail_under) == (None, None, 1, None)
    assert (args.json, args.verbose, args.list, args.validate) == (False, False, False, False)
    args = cli.build_parser().parse_args(["eval", "--scenario", "a", "--scenario", "b", "--repeat", "3"])
    assert (args.scenario, args.repeat) == (["a", "b"], 3)


def test_eval_needs_neither_docker_nor_a_workspace(monkeypatch, eval_output):
    monkeypatch.setattr(cli, "preflight", lambda cfg: pytest.fail("eval must not check Docker or the workspace"))
    assert cli.main(["--lang", "en", "eval", "--list"]) == 0
    assert "healthcheck-port" in eval_output.getvalue()


def test_eval_reports_invalid_scenarios(eval_output, tmp_path):
    assert cli.main(["--lang", "en", "eval", "--scenarios-dir", str(tmp_path)]) == 2
    assert "No scenario files" in eval_output.getvalue()
    assert cli.main(["--lang", "en", "eval", "--scenario", "nope", "--list"]) == 2
    assert "Unknown scenario(s): nope" in eval_output.getvalue()


def test_eval_stops_when_a_model_is_missing(monkeypatch, eval_output):
    monkeypatch.setattr(cli, "_check_ollama", lambda cfg: False)
    assert cli.main(["--lang", "en", "eval", "--scenario", "healthcheck-port"]) == 1


@needs_git
def test_eval_validate_needs_no_model(monkeypatch, eval_output):
    monkeypatch.setattr(cli, "_check_ollama", lambda cfg: pytest.fail("--validate must not need Ollama"))
    monkeypatch.setattr(cli, "spinner", lambda message: nullcontext())
    assert cli.main(["--lang", "en", "eval", "--validate", "--scenario", "healthcheck-port"]) == 0
    assert "1/1 scenario(s) valid." in eval_output.getvalue()


@needs_git
def test_eval_prints_one_line_per_run_and_a_table(eval_with, eval_output):
    eval_with(reference_team)
    argv = ["--lang", "en", "--model", "qwen3:4b", "eval", "--scenario", "healthcheck-port", "--scenario", "healthy-stack"]
    assert cli.main(argv) == 0
    text = eval_output.getvalue()
    assert "healthcheck-port · " in text and "Evaluation · qwen3:4b · 2 scenario(s) × 1" in text
    assert "Passed 2/2 runs (100.0%)" in text


@needs_git
def test_eval_json_keeps_stdout_clean(eval_with, eval_output, capsysbinary):
    eval_with(reference_team)
    assert cli.main(["--lang", "en", "--model", "qwen3:4b", "eval", "--scenario", "healthcheck-port", "--json"]) == 0
    report = json.loads(capsysbinary.readouterr().out.decode("utf-8"))
    assert report["total"]["passed"]["ok"] == 1 and report["models"]["resolver"] == "qwen3:4b"


@needs_git
def test_eval_fail_under(eval_with, eval_output):
    eval_with(silent_team)
    assert cli.main(["--lang", "en", "eval", "--scenario", "healthcheck-port", "--fail-under", "50"]) == 1
    assert "Pass rate 0.0% is below --fail-under 50.0%." in eval_output.getvalue()


def test_eval_team_refuses_actions_and_keeps_quiet(tmp_path):
    cfg = Config()
    cfg.model, cfg.fast_model = "qwen3:8b", "qwen3:4b"
    workspace = Workspace(tmp_path)
    tools = build_toolbox(workspace, ProposalStore(workspace))
    briefs = []
    team = cli.eval_team_factory(cfg, verbose=False)(SimpleNamespace(id="demo"), tools, EventLog(), briefs.append)

    assert team.resolver.approver is deny_actions and team.analyst.approver is deny_actions
    assert team.resolver.console.quiet
    assert "propose_change" not in team.analyst.tools.names()
    team._on_brief("report")
    assert briefs == ["report"]


def test_eval_stops_cleanly_on_ctrl_c(monkeypatch):
    def interrupted(cfg, args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_eval", interrupted)
    assert cli.main(["eval"]) == 130
