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
LOOP_MIN_RESTARTS = 3
RECENT_START = timedelta(minutes=5)


@dataclass(frozen=True)
class Issue:
    container: str
    problems: tuple[str, ...]

    @property
    def detail(self) -> str:
        return "; ".join(self.problems)

    def task(self) -> str:
        """Texto da tarefa entregue ao agente."""
        return (
            f"O monitor detectou um problema no container '{self.container}': {self.detail}. "
            "Investigue a causa (inspect, logs, stats) e, se uma ação puder resolver, proponha-a."
        )


# --- funções auxiliares ---------------------------------------------------------

def _oom_suffix(info: dict) -> str:
    return " (OOMKilled: morto por falta de memória)" if info["oom_killed"] else ""


def _age(timestamp: str | None, now: datetime) -> timedelta | None:
    moment = dk.parse_docker_time(timestamp)
    return now - moment if moment else None


def _started_recently(info: dict, now: datetime) -> bool:
    age = _age(info["started_at"], now)
    return age is not None and age <= RECENT_START


def _health_problem(info: dict) -> str | None:
    # Containers parados guardam o último status do healthcheck, então só vale para os que estão rodando.
    if info["status"] == "running" and info["health"] == "unhealthy":
        return f"healthcheck falhando ({info['health_failing_streak']} falhas seguidas)"
    return None


def _restart_problem(info: dict, previous: int | None, now: datetime) -> str | None:
    if info["status"] != "running":
        return None
    count = info["restart_count"]
    if previous is not None and count > previous:
        return f"reiniciou {count - previous}x desde a última verificação{_oom_suffix(info)}"
    if previous is None and count >= LOOP_MIN_RESTARTS and _started_recently(info, now):
        # Primeira verificação: muitos reinícios e acabou de subir = provável loop.
        return f"já reiniciou {count}x e subiu há poucos minutos (possível loop){_oom_suffix(info)}"
    return None


# --- monitor --------------------------------------------------------------------

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
        now = datetime.now(timezone.utc)
        infos = dk.inspect_containers(self._watched_names())
        return [issue for info in infos if (issue := self._check(info, now))]

    def due(self, issues: list[Issue]) -> list[Issue]:
        """Filtra os problemas que ainda não foram alertados dentro do cooldown."""
        now = time.monotonic()
        fresh = [issue for issue in issues if self._is_due(issue.container, now)]
        for issue in fresh:
            self._alerted[issue.container] = now
        return fresh

    def _watched_names(self) -> list[str]:
        names = [c["name"] for c in dk.list_containers(True)]
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
        problems = tuple(p for p in found if p)
        return Issue(info["name"], problems) if problems else None

    def _remember_restarts(self, info: dict) -> int | None:
        """Guarda o restart_count atual e devolve o da varredura anterior."""
        previous = self._restart_counts.get(info["name"])
        self._restart_counts[info["name"]] = info["restart_count"]
        return previous

    # --- regras que dependem da configuração do monitor ---

    def _state_problem(self, info: dict, now: datetime) -> str | None:
        status = info["status"]
        if status == "restarting":
            return (
                f"em loop de reinício ({info['restart_count']} reinícios, "
                f"último exit code {info['exit_code']}){_oom_suffix(info)}"
            )
        if status == "dead":
            return "está no estado 'dead'"
        if status == "exited" and self._failed_recently(info, now):
            return f"parou com exit code {info['exit_code']}{_oom_suffix(info)}"
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
        return f"{len(errors)} linhas de erro nos logs nos últimos {self.log_window}s, ex.: {errors[-1][:200]}"

    def _error_lines(self, container: str) -> list[str]:
        logs = dk.container_logs(container, tail=dk.MAX_LOG_LINES, since=f"{self.log_window}s")
        return [line for line in logs.splitlines() if ERROR_RE.search(line)]
