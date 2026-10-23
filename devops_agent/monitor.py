"""Monitor: finds container problems with plain rules (no model involved)
and only hands them to the agent when something is wrong."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import docker_tools as dk
from .i18n import t
from .redaction import redact

ERROR_RE = re.compile(
    r"\b(ERROR|FATAL|CRITICAL|PANIC)\b|panic:|Traceback \(most recent call last\)|\bException\b|level=error|\"level\":\s*\"error\""
)
LOOP_MIN_RESTARTS = 3
RECENT_START = timedelta(minutes=5)
EXAMPLE_CHARS = 200


@dataclass(frozen=True)
class Issue:
    container: str
    problems: tuple[str, ...]

    @property
    def detail(self) -> str:
        return "; ".join(self.problems)

    def task(self) -> str:
        """Task text handed to the agent."""
        return t("monitor.task", container=self.container, detail=self.detail)


# --- Helpers ----------------------------------------------------------------------------------------

def _oom_suffix(info: dict) -> str:
    return t("monitor.oom") if info["oom_killed"] else ""


def _age(timestamp: str | None, now: datetime) -> timedelta | None:
    moment = dk.parse_docker_time(timestamp)
    return now - moment if moment else None


def _started_recently(info: dict, now: datetime) -> bool:
    age = _age(info["started_at"], now)
    return age is not None and age <= RECENT_START


def _health_problem(info: dict) -> str | None:
    # Stopped containers keep their last health status, so the rule only applies to running ones.
    if info["status"] == "running" and info["health"] == "unhealthy":
        return t("monitor.unhealthy", streak=info["health_failing_streak"])
    return None


def _restart_problem(info: dict, previous: int | None, now: datetime) -> str | None:
    if info["status"] != "running":
        return None
    count = info["restart_count"]
    if previous is not None and count > previous:
        return t("monitor.restarted", count=count - previous, oom=_oom_suffix(info))
    if previous is None and count >= LOOP_MIN_RESTARTS and _started_recently(info, now):
        # First scan: many restarts and it just came up again = probable loop.
        return t("monitor.probable_loop", count=count, oom=_oom_suffix(info))
    return None


# --- Monitor ----------------------------------------------------------------------------------------

class Monitor:
    def __init__(
        self,
        only: set[str] | None = None,
        scan_logs: bool = False,
        log_window: int = 30,
        log_threshold: int = 3,
        cooldown: int = 600,
        ignore_exited_older_than: timedelta = timedelta(hours=24),
    ):
        self.only = only or set()
        self.scan_logs = scan_logs
        self.log_window = log_window
        self.log_threshold = log_threshold
        self.cooldown = cooldown
        self.ignore_exited_older_than = ignore_exited_older_than
        self._restart_counts: dict[str, int] = {}
        self._alerted: dict[str, float] = {}

    def scan(self) -> list[Issue]:
        """Returns every container that has a problem right now."""
        now = datetime.now(timezone.utc)
        infos = dk.inspect_containers(self._watched_names())
        return [issue for info in infos if (issue := self._check(info, now))]

    def due(self, issues: list[Issue]) -> list[Issue]:
        """Keeps only the issues not alerted within the cooldown."""
        now = time.monotonic()
        fresh = [issue for issue in issues if self._is_due(issue.container, now)]
        for issue in fresh:
            self._alerted[issue.container] = now
        return fresh

    def _watched_names(self) -> list[str]:
        names = [container["name"] for container in dk.list_containers(True)]
        return [name for name in names if not self.only or name in self.only]

    def _is_due(self, container: str, now: float) -> bool:
        last = self._alerted.get(container)
        return last is None or now - last >= self.cooldown

    def _check(self, info: dict, now: datetime) -> Issue | None:
        previous = self._remember_restarts(info)
        found = (
            self._state_problem(info, now),
            _health_problem(info),
            _restart_problem(info, previous, now),
            self._log_problem(info),
        )
        problems = tuple(problem for problem in found if problem)
        return Issue(info["name"], problems) if problems else None

    def _remember_restarts(self, info: dict) -> int | None:
        """Stores the current restart_count and returns the one from the previous scan."""
        previous = self._restart_counts.get(info["name"])
        self._restart_counts[info["name"]] = info["restart_count"]
        return previous

    # --- Rules that depend on the monitor settings ---

    def _state_problem(self, info: dict, now: datetime) -> str | None:
        status = info["status"]
        if status == "restarting":
            return t(
                "monitor.restarting", count=info["restart_count"], exit_code=info["exit_code"], oom=_oom_suffix(info)
            )
        if status == "dead":
            return t("monitor.dead")
        if status == "exited" and self._failed_recently(info, now):
            return t("monitor.exited", exit_code=info["exit_code"], oom=_oom_suffix(info))
        return None

    def _failed_recently(self, info: dict, now: datetime) -> bool:
        failed = info["exit_code"] != 0 or info["oom_killed"]
        age = _age(info["finished_at"], now)
        return failed and (age is None or age <= self.ignore_exited_older_than)

    def _log_problem(self, info: dict) -> str | None:
        if not self.scan_logs or info["status"] != "running":
            return None
        errors = self._error_lines(info["name"])
        if len(errors) < self.log_threshold:
            return None
        example = redact(errors[-1])[:EXAMPLE_CHARS]
        return t("monitor.log_errors", count=len(errors), window=self.log_window, example=example)

    def _error_lines(self, container: str) -> list[str]:
        logs = dk.container_logs(container, tail=dk.MAX_LOG_LINES, since=f"{self.log_window}s")
        return [line for line in logs.splitlines() if ERROR_RE.search(line)]
