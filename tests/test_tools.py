import json

import pytest

from devops_agent.proposals import Proposal, ProposalStore
from devops_agent.tools import DOCKER_TOOLS, Tool, Toolbox, _action_tool, build_toolbox, proposal_tool
from devops_agent.workspace import Workspace

ACTIONS = {"restart_container", "start_container", "stop_container"}
WORKSPACE_TOOLS = {"list_files", "read_file", "search_files", "git_status", "git_log", "git_diff", "collect_diagnostics"}


def echo_tool(**overrides) -> Tool:
    fields = dict(
        name="echo",
        description="Returns its arguments.",
        params={"container": {"type": "string"}, "tail": {"type": "integer"}},
        required=("container",),
        func=lambda **kwargs: kwargs,
    )
    fields.update(overrides)
    return Tool(**fields)


@pytest.fixture
def full_toolbox(tmp_path) -> Toolbox:
    workspace = Workspace(tmp_path)
    return build_toolbox(workspace, ProposalStore(workspace))


# --- Tool ------------------------------------------------------------------------------------------

def test_run_ignores_invented_and_empty_arguments():
    result = echo_tool().run({"container": "api", "tail": None, "invented": 1, "": "x"})
    assert json.loads(result) == {"container": "api"}


def test_run_requires_mandatory_arguments():
    with pytest.raises(ValueError, match="missing parameters: container"):
        echo_tool().run({"tail": 10})


def test_run_treats_empty_string_as_missing():
    with pytest.raises(ValueError):
        echo_tool().run({"container": ""})


def test_run_keeps_strings_and_serializes_other_results_as_json():
    assert echo_tool(func=lambda container: "text").run({"container": "a"}) == "text"
    assert echo_tool(func=lambda container: {"nome": "ação"}).run({"container": "a"}) == '{"nome": "ação"}'


def test_schema_follows_ollama_function_format():
    schema = echo_tool().schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    assert schema["function"]["parameters"] == {
        "type": "object",
        "properties": {"container": {"type": "string"}, "tail": {"type": "integer"}},
        "required": ["container"],
    }


def test_action_tool_always_requires_approval():
    tool = _action_tool("pause_container", "Pauses a container.", lambda container: "ok")
    assert tool.needs_approval is True
    assert tool.required == ("container",)
    assert tool.description.endswith("Requires human approval.")


# --- Toolbox -----------------------------------------------------------------------------------------

def test_default_toolbox_has_only_docker_tools():
    assert build_toolbox().names() == [tool.name for tool in DOCKER_TOOLS]


def test_full_toolbox_adds_workspace_and_proposal_tools(full_toolbox):
    assert WORKSPACE_TOOLS | {"propose_change"} <= set(full_toolbox.names())


def test_only_container_actions_need_approval(full_toolbox):
    assert {tool.name for tool in full_toolbox.by_name.values() if tool.needs_approval} == ACTIONS


def test_toolbox_indexes_are_consistent(full_toolbox):
    assert [schema["function"]["name"] for schema in full_toolbox.schemas] == full_toolbox.names()
    assert full_toolbox.get("missing") is None


def test_logs_tool_keeps_the_end_of_long_output():
    assert Toolbox(DOCKER_TOOLS).get("get_container_logs").keep == "tail"


def test_propose_change_reports_how_to_review_the_proposal():
    class FakeStore:
        def create(self, title, explanation, edits):
            self.received = (title, explanation, edits)
            return Proposal("agent/fix-port-abc123", "c0ffee", title, explanation)

    store = FakeStore()
    edits = [{"path": "a.yml", "old_text": "", "new_text": "x"}]
    output = proposal_tool(store).run({"title": "Fix port", "explanation": "Wrong port", "edits": edits})
    assert store.received == ("Fix port", "Wrong port", edits)
    assert "abc123" in output and "/apply abc123" in output
