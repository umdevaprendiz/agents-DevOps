import threading

from devops_agent.monitor import Issue
from devops_agent.workers import Investigator

TIMEOUT = 5  # seconds; keeps a broken test from hanging forever


class Recorder:
    def __init__(self):
        self.results: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def on_result(self, issue: Issue, answer: str) -> None:
        with self._lock:
            self.results.append((issue.container, answer))

    def on_error(self, issue: Issue, error: Exception) -> None:
        with self._lock:
            self.errors.append((issue.container, str(error)))


def issue(name: str) -> Issue:
    return Issue(name, ("problem",))


def make(investigate, workers=2) -> tuple[Investigator, Recorder]:
    recorder = Recorder()
    return Investigator(investigate, workers, recorder.on_result, recorder.on_error), recorder


def test_every_issue_gets_a_result():
    investigator, recorder = make(lambda i: f"checked {i.container}")
    for name in ("a", "b", "c"):
        assert investigator.submit(issue(name))
    investigator.wait()
    assert sorted(recorder.results) == [("a", "checked a"), ("b", "checked b"), ("c", "checked c")]
    assert investigator.busy() == 0


def test_issues_run_in_parallel():
    barrier = threading.Barrier(2, timeout=TIMEOUT)

    def investigate(i):
        barrier.wait()  # only passes when both investigations run at the same time
        return "ok"

    investigator, recorder = make(investigate, workers=2)
    investigator.submit(issue("a"))
    investigator.submit(issue("b"))
    investigator.wait()
    assert recorder.errors == []
    assert len(recorder.results) == 2


def test_same_container_is_not_queued_twice():
    release = threading.Event()
    investigator, recorder = make(lambda i: "ok" if release.wait(TIMEOUT) else "timeout")

    assert investigator.submit(issue("api"))
    assert not investigator.submit(issue("api"))
    assert investigator.busy() == 1

    release.set()
    investigator.wait()
    assert investigator.submit(issue("api"))  # accepted again once the first one finished
    investigator.wait()
    assert recorder.results == [("api", "ok"), ("api", "ok")]


def test_a_failed_investigation_does_not_stop_the_worker():
    def investigate(i):
        if i.container == "bad":
            raise RuntimeError("model crashed")
        return "ok"

    investigator, recorder = make(investigate, workers=1)
    investigator.submit(issue("bad"))
    investigator.submit(issue("good"))
    investigator.wait()
    assert recorder.errors == [("bad", "model crashed")]
    assert recorder.results == [("good", "ok")]


def test_there_is_always_at_least_one_worker():
    investigator, _ = make(lambda i: "ok", workers=0)
    assert investigator.size == 1
