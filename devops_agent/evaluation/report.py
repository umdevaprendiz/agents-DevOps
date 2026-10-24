"""Evaluation output in the terminal."""
from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from ..i18n import t
from .results import RunResult, Summary, Tally, by_scenario, summarize
from .runner import Validation
from .scenario import Scenario

CHECK_LABELS = {"diagnosis": "eval.col.diagnosis", "fix": "eval.col.fix", "no_changes": "eval.col.no_changes"}


def models_label(resolver: str, analyst: str | None) -> str:
    return t("eval.models_two", resolver=resolver, analyst=analyst) if analyst else resolver


def show_scenarios(console: Console, scenarios: list[Scenario]) -> None:
    table = Table(title=t("eval.list_title"), title_justify="left")
    for key in ("eval.col.scenario", "eval.col.title", "eval.col.focus", "eval.col.checks"):
        table.add_column(t(key))
    for scenario in scenarios:
        focus = scenario.focus or t("eval.focus_everything")
        table.add_row(scenario.id, escape(scenario.title), escape(focus), ", ".join(_checks(scenario)))
    console.print(table)


def _checks(scenario: Scenario) -> list[str]:
    expect = scenario.expect
    flags = (("eval.col.diagnosis", expect.diagnosis), ("eval.col.fix", expect.fix),
             ("eval.col.no_changes", expect.no_changes))
    return [t(key) for key, present in flags if present]


# --- Runs -----------------------------------------------------------------------------------------------

def run_label(scenario: Scenario, attempt: int, repeat: int, index: int, total: int) -> str:
    return t("eval.running", index=index, total=total, scenario=scenario.id, attempt=attempt, repeat=repeat)


def show_run(console: Console, result: RunResult) -> None:
    """One line per finished run, so a long evaluation shows progress."""
    if result.error:
        console.print(f"[red]✗[/] {escape(t('eval.run_error', scenario=result.scenario, error=result.error))}")
        return
    mark = "[green]✓[/]" if result.passed else "[red]✗[/]"
    line = t("eval.run_line", scenario=result.scenario, seconds=result.seconds, tools=result.tool_calls,
             proposals=result.proposals)
    failed = [t(CHECK_LABELS[name]) for name in result.failed_checks()]
    detail = f" [red]({escape(t('eval.failed_checks', checks=', '.join(failed)))})[/]" if failed else ""
    console.print(f"{mark} {escape(line)}{detail}")


def show_results(console: Console, results: list[RunResult], models: str, repeat: int) -> None:
    summaries = by_scenario(results)
    title = t("eval.title", models=models, scenarios=len(summaries), repeat=repeat)
    columns = _columns(summaries)
    table = Table(title=escape(title), title_justify="left")
    for key in columns:
        table.add_column(t(key), justify="left" if key == "eval.col.scenario" else "right")
    for summary in summaries:
        table.add_row(*_cells(summary, columns))
    console.print(table)
    console.print(_total_line(summarize("total", results)))


def _columns(summaries: list[Summary]) -> list[str]:
    optional = {
        "eval.col.analyst": any(s.analyst.total for s in summaries),
        "eval.col.no_changes": any(s.no_changes.total for s in summaries),
    }
    columns = ["eval.col.scenario", "eval.col.passed", "eval.col.diagnosis", "eval.col.analyst", "eval.col.fix",
               "eval.col.no_changes", "eval.col.tools", "eval.col.denied", "eval.col.time"]
    return [key for key in columns if optional.get(key, True)]


def _cells(summary: Summary, columns: list[str]) -> list[str]:
    values = {
        "eval.col.scenario": escape(summary.name),
        "eval.col.passed": _score(summary.passed),
        "eval.col.diagnosis": _score(summary.diagnosis),
        "eval.col.analyst": _score(summary.analyst),
        "eval.col.fix": _score(summary.fix),
        "eval.col.no_changes": _score(summary.no_changes),
        "eval.col.tools": str(summary.tool_calls),
        "eval.col.denied": str(summary.denied),
        "eval.col.time": f"{summary.seconds}s",
    }
    return [values[key] for key in columns]


def _score(score: Tally) -> str:
    if not score.total:
        return "[dim]-[/]"
    style = "green" if score.ok == score.total else "red" if score.ok == 0 else "yellow"
    return f"[{style}]{score}[/]"


def _total_line(total: Summary) -> str:
    text = t("eval.total", passed=str(total.passed), rate=total.passed.percent, diagnosis=str(total.diagnosis),
             fix=str(total.fix), seconds=total.seconds)
    return f"[bold]{escape(text)}[/]"


# --- Scenario check (eval --validate) ------------------------------------------------------------------------

def show_validation(console: Console, validations: list[Validation]) -> None:
    table = Table(title=t("eval.validate_title"), title_justify="left")
    for key in ("eval.col.scenario", "eval.col.reference", "eval.col.baseline", "eval.col.result"):
        table.add_column(t(key))
    for item in validations:
        table.add_row(item.scenario.id, _verdict(item.reference.passed), _verdict(item.baseline.passed), _problem(item))
    console.print(table)
    valid = sum(1 for item in validations if item.ok)
    console.print(t("eval.validate_summary", ok=valid, total=len(validations)))


def _verdict(passed: bool) -> str:
    return f"[green]{t('eval.passes')}[/]" if passed else f"[yellow]{t('eval.fails')}[/]"


def _problem(item: Validation) -> str:
    if not item.reference.passed:
        reason = item.reference.error or ", ".join(t(CHECK_LABELS[name]) for name in item.reference.failed_checks())
        return f"[red]{escape(t('eval.reference_fails', reason=reason))}[/]"
    if item.too_weak:
        return f"[red]{escape(t('eval.too_weak'))}[/]"
    return f"[green]{t('eval.valid')}[/]"
