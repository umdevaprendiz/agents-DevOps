import io
from types import SimpleNamespace

import pytest
from rich.console import Console
from rich.prompt import InvalidResponse

from devops_agent import cli
from devops_agent.monitor import Issue
from devops_agent.ui import YesNoConfirm


@pytest.fixture
def output(monkeypatch):
    """Captura o que a CLI escreve no terminal."""
    buffer = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, width=120))
    return buffer


class FakeAgent:
    def __init__(self):
        self.resets = 0
        self.runs = []

    def reset(self):
        self.resets += 1

    def run(self, task, require_evidence=False):
        self.runs.append((task, require_evidence))
        return f"resposta {len(self.runs)}"


# --- argumentos -------------------------------------------------------------------------

def test_parse_only_splits_and_trims_names():
    assert cli._parse_only(" api, web ,,db ") == {"api", "web", "db"}
    assert cli._parse_only(None) is None


def test_watch_defaults():
    args = cli.build_parser().parse_args(["watch"])
    assert (args.interval, args.cooldown, args.scan_logs, args.only) == (30, 600, False, None)


def test_model_option_overrides_config():
    args = cli.build_parser().parse_args(["--model", "qwen3:8b", "check"])
    assert cli._build_config(args).model == "qwen3:8b"


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


# --- comandos ----------------------------------------------------------------------------

def test_main_stops_when_preflight_fails(monkeypatch):
    monkeypatch.setattr(cli, "preflight", lambda cfg: False)
    assert cli.main(["check"]) == 1


def test_check_without_issues(output):
    cli.cmd_check(FakeAgent(), SimpleNamespace(scan=lambda: []))
    assert "Nenhum problema encontrado." in output.getvalue()


def test_each_issue_is_investigated_from_scratch_with_evidence(monkeypatch, output):
    shown = []
    monkeypatch.setattr(cli, "show_answer", shown.append)
    agent = FakeAgent()
    cli.handle_issues(agent, [Issue("api", ("parou",)), Issue("web", ("unhealthy",))])
    assert agent.resets == 2
    assert [require for _, require in agent.runs] == [True, True]
    assert "'api'" in agent.runs[0][0]
    assert shown == ["resposta 1", "resposta 2"]


def test_chat_turn_handles_reset_command(output):
    agent = FakeAgent()
    cli._chat_turn(agent, "/limpar")
    assert agent.resets == 1 and agent.runs == []


def test_chat_turn_ignores_empty_input():
    agent = FakeAgent()
    cli._chat_turn(agent, "")
    assert agent.runs == []


# --- confirmação --------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [("s", True), ("SIM", True), ("y", True), ("n", False), ("não", False), ("no", False)])
def test_yes_no_confirm_accepts_portuguese_and_english(value, expected):
    assert YesNoConfirm("Permitir?").process_response(value) is expected


def test_yes_no_confirm_rejects_other_answers():
    with pytest.raises(InvalidResponse):
        YesNoConfirm("Permitir?").process_response("talvez")
