import json

import pytest

from devops_agent.tools import TOOL_SCHEMAS, TOOLS, TOOLS_BY_NAME, Tool, _action_tool

ACTIONS = {"restart_container", "start_container", "stop_container"}


def echo_tool(**overrides) -> Tool:
    fields = dict(
        name="echo",
        description="Devolve os argumentos.",
        params={"container": {"type": "string"}, "tail": {"type": "integer"}},
        required=("container",),
        func=lambda **kwargs: kwargs,
    )
    fields.update(overrides)
    return Tool(**fields)


def test_run_ignores_invented_and_empty_arguments():
    result = echo_tool().run({"container": "api", "tail": None, "invented": 1, "": "x"})
    assert json.loads(result) == {"container": "api"}


def test_run_requires_mandatory_arguments():
    with pytest.raises(ValueError, match="faltam parâmetros: container"):
        echo_tool().run({"tail": 10})


def test_run_treats_empty_string_as_missing():
    with pytest.raises(ValueError):
        echo_tool().run({"container": ""})


def test_run_keeps_strings_and_serializes_other_results_as_json():
    assert echo_tool(func=lambda container: "texto").run({"container": "a"}) == "texto"
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
    tool = _action_tool("pause_container", "Pausa um container.", lambda container: "ok")
    assert tool.needs_approval is True
    assert tool.required == ("container",)
    assert tool.description.endswith("Exige aprovação humana.")


def test_only_state_changing_tools_need_approval():
    assert {t.name for t in TOOLS if t.needs_approval} == ACTIONS


def test_catalog_indexes_are_consistent():
    assert len(TOOLS_BY_NAME) == len(TOOLS)
    assert [s["function"]["name"] for s in TOOL_SCHEMAS] == [t.name for t in TOOLS]


def test_logs_tool_keeps_the_end_of_long_output():
    assert TOOLS_BY_NAME["get_container_logs"].keep == "tail"
