import asyncio

import pytest
from pydantic import ValidationError

from freecad_fem_mcp.models import AddConstraintRequest
from freecad_fem_mcp.server import TOOL_NAMES, create_server, get_tool_names


class FakeClient:
    def __init__(self):
        self.calls = []

    async def call_async(self, method, params):
        self.calls.append((method, params))
        return {"method": method, "params": params}


def test_fixed_tool_surface_has_no_generic_escape_hatches() -> None:
    assert TOOL_NAMES == (
        "get_status",
        "inspect_document",
        "get_selection",
        "set_view",
        "capture_gui",
        "open_model",
        "save_document",
        "create_analysis",
        "assign_material",
        "add_constraint",
        "create_mesh",
        "validate_analysis",
        "start_analysis",
        "get_job",
        "list_jobs",
        "cancel_job",
        "get_results",
        "show_result",
    )
    app = create_server(FakeClient())
    assert set(get_tool_names(app)) == set(TOOL_NAMES)


def test_tool_calls_cross_only_the_generic_bridge_boundary() -> None:
    client = FakeClient()
    app = create_server(client)
    tools = getattr(getattr(app, "_tool_manager", None), "_tools", None)
    if tools is None:
        tools = getattr(app, "_tools")
    entry = tools["get_status"]
    function = getattr(entry, "fn", entry)
    result = asyncio.run(function())
    assert result["method"] == "status"
    assert client.calls[0][0] == "status"
    assert client.calls[0][1]["action"] == "get"


def test_add_constraint_targets_use_object_name_and_subelements() -> None:
    request = AddConstraintRequest(
        analysis_id="Analysis",
        constraint_type="fixed",
        targets=[{"object_name": "Cantilever", "subelements": ["Face1"]}],
    )
    assert request.targets[0].object_name == "Cantilever"
    assert request.targets[0].subelements == ["Face1"]

    with pytest.raises(ValidationError):
        AddConstraintRequest(
            analysis_id="Analysis",
            constraint_type="fixed",
            targets=[{"object_id": "Cantilever", "subelements": ["Face1"]}],
        )

    app = create_server(FakeClient())
    tools = getattr(getattr(app, "_tool_manager", None), "_tools", None) or getattr(app, "_tools")
    schema = getattr(tools["add_constraint"], "parameters", {})
    entity_schema = schema["$defs"]["EntityRef"]
    assert "object_name" in entity_schema["required"]
    assert "object_id" not in entity_schema["properties"]
    assert "Cantilever" in entity_schema["properties"]["object_name"]["description"]
    assert "Face1" in entity_schema["properties"]["subelements"]["description"]
