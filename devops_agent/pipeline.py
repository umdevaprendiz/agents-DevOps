"""Two models working together: a fast one investigates, a heavy one resolves.

The analyst (fast model, read-only tools) explores the containers, logs and files and writes a
short report with evidence. The resolver (heavy model, every tool) checks that evidence, explains
the problem and proposes the fix. With no fast model configured, the resolver does everything.
"""
from __future__ import annotations

from typing import Callable, Protocol

from .i18n import t


class Runner(Protocol):
    def run(self, task: str, require_evidence: bool = False) -> str: ...

    def reset(self) -> None: ...


class Team:
    def __init__(self, resolver: Runner, analyst: Runner | None = None, on_brief: Callable[[str], None] | None = None):
        self.resolver = resolver
        self.analyst = analyst
        self._on_brief = on_brief or (lambda brief: None)

    @property
    def two_stage(self) -> bool:
        return self.analyst is not None

    def run(self, task: str, require_evidence: bool = False) -> str:
        if self.analyst is None:
            return self.resolver.run(task, require_evidence)
        brief = self._investigate(task)
        # The brief already carries the evidence, so the resolver is not forced to repeat the tool calls.
        return self.resolver.run(t("prompt.resolve", task=task, brief=brief))

    def reset(self) -> None:
        self.resolver.reset()
        if self.analyst is not None:
            self.analyst.reset()

    def _investigate(self, task: str) -> str:
        brief = self.analyst.run(t("prompt.analyze", task=task), require_evidence=True)
        self._on_brief(brief)
        return brief
