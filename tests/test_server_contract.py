import asyncio

import pytest
from pydantic import ValidationError

from freecad_fem_mcp.models import AddConstraintRequest
from freecad_fem_mcp.server import PUBLIC_TOOL_ACTIONS, TOOL_NAMES, create_server, get_tool_names


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
        "add_load",
        "add_remote_load",
        "add_remote_displacement",
        "add_boundary_condition",
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


def test_typed_load_and_boundary_tools_use_dedicated_bridge_methods() -> None:
    assert PUBLIC_TOOL_ACTIONS["add_load"] == ("load", "add")
    assert PUBLIC_TOOL_ACTIONS["add_boundary_condition"] == ("boundary_condition", "add")

    client = FakeClient()
    app = create_server(client)
    tools = getattr(getattr(app, "_tool_manager", None), "_tools", None) or getattr(app, "_tools")

    load_fn = getattr(tools["add_load"], "fn", tools["add_load"])
    asyncio.run(
        load_fn(
            analysis_id="Analysis",
            load_type="force",
            force_n=10.0,
            targets=[{"object_name": "Cantilever", "subelements": ["Face1"]}],
        )
    )
    remote_fn = getattr(tools["add_remote_load"], "fn", tools["add_remote_load"])
    asyncio.run(
        remote_fn(
            analysis_id="Analysis",
            targets=[{"object_name": "Cantilever", "subelements": ["Face1"]}],
            reference_point_m=[0.0, 0.0, 0.0],
            force_n=[10.0, 0.0, 0.0],
        )
    )
    remote_displacement_fn = getattr(
        tools["add_remote_displacement"], "fn", tools["add_remote_displacement"]
    )
    asyncio.run(
        remote_displacement_fn(
            analysis_id="Analysis",
            targets=[{"object_name": "Cantilever", "subelements": ["Face1"]}],
            reference_point_m=[0.0, 0.0, 0.0],
            translation_m=[0.0, None, None],
            rotation_rad=[None, None, None],
        )
    )
    boundary_fn = getattr(tools["add_boundary_condition"], "fn", tools["add_boundary_condition"])
    asyncio.run(
        boundary_fn(
            analysis_id="Analysis",
            boundary_type="displacement",
            displacement_m=[0.0, 0.0, 0.001],
        )
    )

    assert client.calls[0][0] == "load"
    assert client.calls[0][1]["action"] == "add"
    assert client.calls[0][1]["load_type"] == "force"
    assert client.calls[0][1]["force_n"] == 10.0
    assert PUBLIC_TOOL_ACTIONS["add_remote_load"] == ("remote_load", "add")
    assert client.calls[1][0] == "remote_load"
    assert client.calls[1][1]["action"] == "add"
    assert client.calls[1][1]["reference_point_m"] == [0.0, 0.0, 0.0]
    assert client.calls[1][1]["force_n"] == [10.0, 0.0, 0.0]
    assert PUBLIC_TOOL_ACTIONS["add_remote_displacement"] == ("remote_displacement", "add")
    assert client.calls[2][0] == "remote_displacement"
    assert client.calls[2][1]["action"] == "add"
    assert client.calls[2][1]["translation_m"] == [0.0, None, None]
    assert client.calls[3][0] == "boundary_condition"
    assert client.calls[3][1]["action"] == "add"
    assert client.calls[3][1]["boundary_type"] == "displacement"

    with pytest.raises(ValidationError):
        asyncio.run(
            load_fn(
                analysis_id="Analysis",
                load_type="gravity",
                acceleration_m_s2=[0.0, 0.0, 0.0],
            )
        )

    load_schema = getattr(tools["add_load"], "parameters", {})
    assert load_schema["additionalProperties"] is False
    acceleration_schema = load_schema["properties"]["acceleration_m_s2"]["anyOf"][0]
    assert acceleration_schema["maxItems"] == 3
    assert acceleration_schema["minItems"] == 3
    assert "centrifugal" in load_schema["properties"]["load_type"]["enum"]
    frequency_schema = load_schema["properties"]["rotation_frequency_hz"]["anyOf"][0]
    assert frequency_schema["exclusiveMinimum"] == 0
    assert frequency_schema["maximum"] == 1e9
    axis_schema = load_schema["properties"]["axis"]["anyOf"][0]
    assert "EntityRef" in axis_schema["$ref"]

    remote_schema = getattr(tools["add_remote_load"], "parameters", {})
    assert remote_schema["additionalProperties"] is False
    assert remote_schema["properties"]["targets"]["minItems"] == 1
    assert remote_schema["properties"]["reference_point_m"]["minItems"] == 3
    assert remote_schema["properties"]["reference_point_m"]["items"]["le"] == 1e9
    force_schema = remote_schema["properties"]["force_n"]["anyOf"][0]
    assert force_schema["items"]["le"] == 1e15
    assert "coordinate_system" not in remote_schema["properties"]

    remote_displacement_schema = getattr(tools["add_remote_displacement"], "parameters", {})
    assert remote_displacement_schema["additionalProperties"] is False
    assert remote_displacement_schema["properties"]["targets"]["minItems"] == 1
    translation_schema = remote_displacement_schema["properties"]["translation_m"]["anyOf"][0]
    assert translation_schema["minItems"] == 3
    assert translation_schema["items"]["anyOf"][0]["le"] == 1e9
    rotation_schema = remote_displacement_schema["properties"]["rotation_rad"]["anyOf"][0]
    assert rotation_schema["items"]["anyOf"][0]["le"] == 1e6
    assert "force_n" not in remote_displacement_schema["properties"]
    assert "coordinate_system" not in remote_displacement_schema["properties"]

    with pytest.raises(ValidationError):
        asyncio.run(
            remote_fn(
                analysis_id="Analysis",
                targets=[{"object_name": "Cantilever", "subelements": ["Face1"]}],
                reference_point_m=[0.0, 0.0, 0.0],
                force_n=[0.0, 0.0, 0.0],
                moment_n_m=[0.0, 0.0, 0.0],
            )
        )

    with pytest.raises(ValidationError):
        asyncio.run(
            remote_displacement_fn(
                analysis_id="Analysis",
                targets=[{"object_name": "Cantilever", "subelements": ["Face1"]}],
                reference_point_m=[0.0, 0.0, 0.0],
                translation_m=[None, None, None],
                rotation_rad=[None, None, None],
            )
        )
