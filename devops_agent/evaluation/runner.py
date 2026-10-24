"""Runs the agent on each scenario, exactly like /debug, and scores what it did."""
from __future__ import annotations

import time
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Callable

from ..commands import debug_task
from ..i18n import t
from ..pipeline import Runner
from ..tools import Tool, Toolbox
from .environment import Environment
from .results import RunResult
from .scenario import Scenario

# (scenario, its toolbox, the event log to fill, where to send the fast model's report) -> the agent
TeamFactory = Callable[[Scenario, Toolbox, "EventLog", Callable[[str], None]], Runner]
Progress = Callable[[Scenario, int], AbstractContextManager]


class EventLog:
    """In-memory audit log: the agent writes its events here and the evaluation counts them."""

    def __init__(self):
        self.events: list[dict] = []

    def log(self, event: str, **data) -> None:
        self.events.append({"event": event, **data})

    def count(self, event: str, **match) -> int:
        return sum(1 for item in self.events if item["event"] == event and _matches(item, match))


def _matches(item: dict, match: dict) -> bool:
    return all(item.get(key) == value for key, value in match.items())


def deny_actions(tool: Tool, args: dict) -> bool:
    """Approver used in the evaluation: container actions are always refused (and counted)."""
    return False


# --- Running ---------------------------------------------------------------------------------------

def evaluate(
    scenarios: list[Scenario],
    make_team: TeamFactory,
    repeat: int = 1,
    progress: Progress | None = None,
    on_result: Callable[[RunResult], None] | None = None,
) -> list[RunResult]:
    """Runs every scenario `repeat` times, one after the other (one model in memory at a time)."""
    results = []
    for scenario in scenarios:
        for attempt in range(1, repeat + 1):
            with (progress or _no_progress)(scenario, attempt):
                result = run_scenario(scenario, make_team, attempt)
            results.append(result)
            if on_result:
                on_result(result)
    return results


def run_scenario(scenario: Scenario, make_team: TeamFactory, attempt: int = 1) -> RunResult:
    with Environment(scenario) as env:
        events, briefs = EventLog(), []
        team = make_team(scenario, env.tools, events, briefs.append)
        answer, error, seconds = _timed_run(team, debug_task(scenario.focus))
        return _score(scenario, env, events, briefs, _Outcome(answer, error, seconds, attempt))


@dataclass(frozen=True)
class _Outcome:
    answer: str
    error: str | None
    seconds: float
    attempt: int


def _timed_run(team: Runner, task: str) -> tuple[str, str | None, float]:
    start = time.perf_counter()
    try:
        answer, error = team.run(task) or "", None
    except Exception as failure:  # Ollama down, model error...: recorded, the next scenario still runs
        answer, error = "", str(failure) or type(failure).__name__
    return answer, error, time.perf_counter() - start


def _score(scenario: Scenario, env: Environment, events: EventLog, briefs: list[str], outcome: _Outcome) -> RunResult:
    proposals = env.proposals.created
    # The cause may be written in the answer or in a proposal's title and explanation.
    text = "\n".join([outcome.answer, *(f"{p.title}\n{p.explanation}" for p in proposals)])
    env.apply_proposals()
    expect = scenario.expect
    return RunResult(
        scenario=scenario.id,
        attempt=outcome.attempt,
        diagnosis=expect.diagnosed(text),
        analyst=expect.diagnosed(briefs[-1]) if briefs else None,
        fix=expect.fixed(env.read),
        no_changes=not proposals if expect.no_changes else None,
        tool_calls=events.count("tool"),
        tool_errors=events.count("tool", ok=False),
        denied=events.count("approval", approved=False),
        proposals=len(proposals),
        seconds=round(outcome.seconds, 1),
        answer=outcome.answer,
        error=outcome.error,
    )


def _no_progress(scenario: Scenario, attempt: int) -> AbstractContextManager:
    return nullcontext()


# --- Checking the scenarios themselves (no model) ----------------------------------------------------------

class ReferenceTeam:
    """Plays a perfect agent: proposes the scenario's reference fix and gives its reference answer."""

    def __init__(self, scenario: Scenario, tools: Toolbox):
        self.scenario = scenario
        self.tools = tools

    def run(self, task: str, require_evidence: bool = False) -> str:
        reference = self.scenario.reference
        if reference.edits:
            args = {"title": reference.title or t("eval.reference_title"), "explanation": reference.answer,
                    "edits": [dict(edit) for edit in reference.edits]}
            self.tools.get("propose_change").run(args)
        return reference.answer

    def reset(self) -> None:
        pass


class SilentTeam:
    """An agent that finds nothing and proposes nothing: no scenario with a bug may pass with it."""

    def run(self, task: str, require_evidence: bool = False) -> str:
        return ""

    def reset(self) -> None:
        pass


@dataclass(frozen=True)
class Validation:
    scenario: Scenario
    reference: RunResult
    baseline: RunResult

    @property
    def too_weak(self) -> bool:
        """Passes without any fix although the scenario has a bug."""
        has_bug = bool(self.scenario.expect.diagnosis or self.scenario.expect.fix)
        return has_bug and self.baseline.passed

    @property
    def ok(self) -> bool:
        return self.reference.passed and not self.too_weak


def validate(scenarios: list[Scenario]) -> list[Validation]:
    """Each scenario must pass with its reference solution and fail when nothing is done."""
    def reference(scenario, tools, events, on_brief):
        return ReferenceTeam(scenario, tools)

    def silent(scenario, tools, events, on_brief):
        return SilentTeam()

    return [Validation(s, run_scenario(s, reference), run_scenario(s, silent)) for s in scenarios]
