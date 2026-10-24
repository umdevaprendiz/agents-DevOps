"""Results of the evaluation runs, their totals and the JSON report."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

ANSWER_CHARS = 4000  # kept per run in the JSON report


@dataclass
class RunResult:
    scenario: str
    attempt: int
    diagnosis: bool | None  # the answer names the cause (None = not scored in this scenario)
    analyst: bool | None  # the fast model's report names the cause (two-model mode only)
    fix: bool | None  # the proposed change fixes the files
    no_changes: bool | None  # healthy scenario: nothing was proposed
    tool_calls: int
    tool_errors: int
    denied: int  # container actions the agent tried (always denied in the evaluation)
    proposals: int
    seconds: float
    answer: str = ""
    error: str | None = None

    @property
    def passed(self) -> bool:
        checks = [value for value in (self.diagnosis, self.fix, self.no_changes) if value is not None]
        return self.error is None and all(checks)

    def failed_checks(self) -> list[str]:
        names = ("diagnosis", "fix", "no_changes")
        return [name for name in names if getattr(self, name) is False]

    def as_dict(self) -> dict:
        data = asdict(self)
        data["answer"] = self.answer[:ANSWER_CHARS]
        return {**data, "passed": self.passed}


@dataclass(frozen=True)
class Tally:
    """How many runs passed one check, out of the runs where it was scored."""

    ok: int = 0
    total: int = 0

    def __str__(self) -> str:
        return f"{self.ok}/{self.total}" if self.total else "-"

    @property
    def rate(self) -> float | None:
        return round(100 * self.ok / self.total, 1) if self.total else None

    @property
    def percent(self) -> float:
        """The rate, with 0.0 when nothing was scored."""
        return self.rate if self.rate is not None else 0.0


def tally(values) -> Tally:
    scored = [value for value in values if value is not None]
    return Tally(sum(1 for value in scored if value), len(scored))


@dataclass(frozen=True)
class Summary:
    """Totals for one scenario, or for every run."""

    name: str
    runs: int
    passed: Tally
    diagnosis: Tally
    analyst: Tally
    fix: Tally
    no_changes: Tally
    tool_calls: float  # average per run
    denied: int
    errors: int
    seconds: float  # average per run

    def as_dict(self) -> dict:
        data = asdict(self)
        for name in ("passed", "diagnosis", "analyst", "fix", "no_changes"):
            score = getattr(self, name)
            data[name] = {"ok": score.ok, "total": score.total, "rate": score.rate}
        return data


def summarize(name: str, results: list[RunResult]) -> Summary:
    runs = len(results) or 1
    return Summary(
        name=name,
        runs=len(results),
        passed=tally(result.passed for result in results),
        diagnosis=tally(result.diagnosis for result in results),
        analyst=tally(result.analyst for result in results),
        fix=tally(result.fix for result in results),
        no_changes=tally(result.no_changes for result in results),
        tool_calls=round(sum(result.tool_calls for result in results) / runs, 1),
        denied=sum(result.denied for result in results),
        errors=sum(1 for result in results if result.error),
        seconds=round(sum(result.seconds for result in results) / runs, 1),
    )


def by_scenario(results: list[RunResult]) -> list[Summary]:
    """One summary per scenario, in the order they ran."""
    groups: dict[str, list[RunResult]] = {}
    for result in results:
        groups.setdefault(result.scenario, []).append(result)
    return [summarize(name, group) for name, group in groups.items()]


def as_json(results: list[RunResult], models: dict, language: str, repeat: int) -> str:
    report = {
        "models": models,
        "language": language,
        "repeat": repeat,
        "total": summarize("total", results).as_dict(),
        "scenarios": [summary.as_dict() for summary in by_scenario(results)],
        "runs": [result.as_dict() for result in results],
    }
    return json.dumps(report, ensure_ascii=False, indent=2)
