"""Parallel investigations: a queue of issues consumed by a pool of worker threads.

The scanner keeps scanning while investigations run. A container that is already queued
or under investigation is not queued again. Threads are daemons, so Ctrl+C exits at once.
The queue sits behind submit()/wait(), which keeps the door open for a distributed queue later.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from .monitor import Issue

Investigate = Callable[[Issue], str]
OnResult = Callable[[Issue, str], None]
OnError = Callable[[Issue, Exception], None]

WAIT_POLL_SECONDS = 0.2


class Investigator:
    def __init__(self, investigate: Investigate, workers: int, on_result: OnResult, on_error: OnError):
        self.size = max(1, workers)
        self._investigate = investigate
        self._on_result = on_result
        self._on_error = on_error
        self._queue: queue.Queue[Issue] = queue.Queue()
        self._busy: set[str] = set()
        self._lock = threading.Lock()
        self._start_threads()

    def submit(self, issue: Issue) -> bool:
        """Queues the issue. Returns False if that container is already queued or being investigated."""
        with self._lock:
            if issue.container in self._busy:
                return False
            self._busy.add(issue.container)
        self._queue.put(issue)
        return True

    def busy(self) -> int:
        """How many containers are queued or under investigation."""
        with self._lock:
            return len(self._busy)

    def wait(self) -> None:
        """Blocks until every submitted issue is done (polls, so Ctrl+C still works on Windows)."""
        while self.busy():
            time.sleep(WAIT_POLL_SECONDS)

    def _start_threads(self) -> None:
        for number in range(1, self.size + 1):
            threading.Thread(target=self._work, name=f"investigator-{number}", daemon=True).start()

    def _work(self) -> None:
        while True:
            issue = self._queue.get()
            try:
                self._handle(issue)
            finally:
                self._release(issue)
                self._queue.task_done()

    def _handle(self, issue: Issue) -> None:
        try:
            answer = self._investigate(issue)
        except Exception as error:  # one failed investigation must not kill the worker
            self._on_error(issue, error)
        else:
            self._on_result(issue, answer)

    def _release(self, issue: Issue) -> None:
        with self._lock:
            self._busy.discard(issue.container)
