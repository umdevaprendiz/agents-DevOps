"""Monitor: detecta problemas nos containers com regras simples (sem gastar o modelo)
e só chama o agente quando encontra algo."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import docker_tools as dk

ERROR_RE = re.compile(
    r"\b(ERROR|FATAL|CRITICAL|PANIC)\b|panic:|Traceback \(most recent call last\)|\bException\b|level=error|\"level\":\s*\"error\""
)


@dataclass(frozen=True)
class Issue:
    container: str
    problems: tuple[str, ...]

    @property
    def detail(self) -> str:
        return "; ".join(self.problems)

    def task(self) -> str:
        return (
            f"O monitor detectou um problema no container '{self.container}': {self.detail}. "
            "Investigue a causa (inspect, logs, stats) e, se uma ação puder resolver, proponha-a."
        )


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
        """Retorna todos os containers com problema neste momento."""
        names = [c["name"] for c in dk.list_containers(True) if not self.only or c["name"] in self.only]
        now = datetime.now(timezone.utc)
        issues = []
        for info in dk.inspect_containers(names):
            problems = self._problems(info, now)
            if problems:
                issues.append(Issue(info["name"], tuple(problems)))
        return issues

    def due(self, issues: list[Issue]) -> list[Issue]:
        """Filtra os problemas que ainda não foram alertados dentro do cooldown."""
        now = time.monotonic()
        fresh = []
        for issue in issues:
            last = self._alerted.get(issue.container)
            if last is None or now - last >= self.cooldown:
                self._alerted[issue.container] = now
                fresh.append(issue)
        return fresh

    def _problems(self, info: dict, now: datetime) -> list[str]:
        name, status = info["name"], info["status"]
        oom = " (OOMKilled: morto por falta de memória)" if info["oom_killed"] else ""
        problems = []

        if status == "restarting":
            problems.append(
                f"em loop de reinício ({info['restart_count']} reinícios, último exit code {info['exit_code']}){oom}"
            )
        elif status == "exited" and (info["exit_code"] != 0 or info["oom_killed"]):
            finished = dk.parse_docker_time(info["finished_at"])
            if finished is None or now - finished <= self.ignore_exited_older_than:
                problems.append(f"parou com exit code {info['exit_code']}{oom}")
        elif status == "dead":
            problems.append("está no estado 'dead'")

        # Containers parados guardam o último status do healthcheck, então só vale para os que estão rodando.
        if status == "running" and info["health"] == "unhealthy":
            problems.append(f"healthcheck falhando ({info['health_failing_streak']} falhas seguidas)")

        previous = self._restart_counts.get(name)
        self._restart_counts[name] = info["restart_count"]
        if status == "running":
            if previous is not None and info["restart_count"] > previous:
                problems.append(f"reiniciou {info['restart_count'] - previous}x desde a última verificação{oom}")
            elif previous is None and info["restart_count"] >= 3 and self._recently_started(info, now):
                # Primeira verificação: muitos reinícios e acabou de subir = provável loop.
                problems.append(f"já reiniciou {info['restart_count']}x e subiu há poucos minutos (possível loop){oom}")

        if self.scan_logs and status == "running":
            logs = dk.container_logs(name, tail=500, since=f"{self.log_window}s")
            errors = [line for line in logs.splitlines() if ERROR_RE.search(line)]
            if len(errors) >= self.log_threshold:
                problems.append(
                    f"{len(errors)} linhas de erro nos logs nos últimos {self.log_window}s, ex.: {errors[-1][:200]}"
                )
        return problems

    @staticmethod
    def _recently_started(info: dict, now: datetime, window: timedelta = timedelta(minutes=5)) -> bool:
        started = dk.parse_docker_time(info["started_at"])
        return started is not None and now - started <= window
