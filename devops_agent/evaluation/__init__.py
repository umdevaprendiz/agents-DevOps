"""Model evaluation: runs the agent on scenarios with known bugs and scores the answers.

Each scenario gets a temporary git repository with its files and a simulated Docker with its
containers, so the evaluation needs neither Docker nor the operator's project, only the models.
"""
from .report import models_label, run_label, show_results, show_run, show_scenarios, show_validation
from .results import RunResult, as_json, summarize
from .runner import EventLog, TeamFactory, deny_actions, evaluate, run_scenario, validate
from .scenario import Scenario, ScenarioError, load_scenarios, select

__all__ = [
    "EventLog", "RunResult", "Scenario", "ScenarioError", "TeamFactory", "as_json", "deny_actions", "evaluate",
    "load_scenarios", "models_label", "run_label", "run_scenario", "select", "show_results", "show_run",
    "show_scenarios", "show_validation", "summarize", "validate",
]
