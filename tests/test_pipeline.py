from devops_agent.i18n import t
from devops_agent.pipeline import Team


class FakeRunner:
    def __init__(self, answer: str):
        self.answer = answer
        self.calls: list[tuple[str, bool]] = []
        self.resets = 0

    def run(self, task, require_evidence=False):
        self.calls.append((task, require_evidence))
        return self.answer

    def reset(self):
        self.resets += 1


def test_without_a_fast_model_the_resolver_does_everything():
    resolver = FakeRunner("final")
    team = Team(resolver)
    assert team.two_stage is False
    assert team.run("debug web", require_evidence=True) == "final"
    assert resolver.calls == [("debug web", True)]


def test_the_analyst_investigates_and_the_resolver_receives_the_brief():
    analyst, resolver = FakeRunner("## Evidence\nwget: connection refused"), FakeRunner("final")
    briefs = []
    team = Team(resolver, analyst, on_brief=briefs.append)

    assert team.run("debug web", require_evidence=True) == "final"

    assert analyst.calls == [(t("prompt.analyze", task="debug web"), True)]
    (resolver_task, resolver_evidence), = resolver.calls
    assert resolver_task == t("prompt.resolve", task="debug web", brief="## Evidence\nwget: connection refused")
    assert resolver_evidence is False  # the brief already carries the evidence
    assert briefs == ["## Evidence\nwget: connection refused"]


def test_reset_clears_both_models():
    analyst, resolver = FakeRunner("a"), FakeRunner("b")
    Team(resolver, analyst).reset()
    assert (analyst.resets, resolver.resets) == (1, 1)


def test_analyst_failures_propagate_before_the_resolver_runs():
    class Broken(FakeRunner):
        def run(self, task, require_evidence=False):
            raise RuntimeError("model crashed")

    resolver = FakeRunner("final")
    try:
        Team(resolver, Broken("")).run("x")
    except RuntimeError:
        pass
    assert resolver.calls == []
