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
        "assign_element_geometry",
        "add_constraint",
        "add_load",
        "add_remote_load",
        "add_remote_displacement",
        "add_boundary_condition",
        "add_connection",
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


def test_connection_tool_forwards_tie_and_contact_routes() -> None:
    client = FakeClient()
    app = create_server(client)
    tools = getattr(getattr(app, "_tool_manager", None), "_tools", None) or getattr(app, "_tools")
    connection_fn = getattr(tools["add_connection"], "fn", tools["add_connection"])
    slave = {"object_name": "Slave", "subelements": ["Face1"]}
    master = {"object_name": "Master", "subelements": ["Face2"]}

    asyncio.run(
        connection_fn(
            analysis_id="Analysis",
            connection_type="tie",
            slave=slave,
            master=master,
            tolerance_m=0.001,
            adjust=True,
        )
    )
    assert client.calls[-1] == (
        "connection",
        {
            "action": "add",
            "analysis_id": "Analysis",
            "connection_type": "tie",
            "slave": slave,
            "master": master,
            "tolerance_m": 0.001,
            "adjust": True,
        },
    )

    asyncio.run(
        connection_fn(
            analysis_id="Analysis",
            connection_type="contact",
            slave=slave,
            master=master,
            surface_behavior="hard",
        )
    )
    assert client.calls[-1][0] == "connection"
    assert client.calls[-1][1]["surface_behavior"] == "hard"
    with pytest.raises(ValidationError):
        asyncio.run(
            connection_fn(
                analysis_id="Analysis",
                connection_type="contact",
                slave=slave,
                master=master,
                surface_behavior="hard",
                tolerance_m=0.1,
            )
        )


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


def test_create_analysis_variants_keep_one_tool_and_forward_controls() -> None:
    client = FakeClient()
    app = create_server(client)
    tools = getattr(getattr(app, "_tool_manager", None), "_tools", None) or getattr(app, "_tools")
    create_fn = getattr(tools["create_analysis"], "fn", tools["create_analysis"])

    asyncio.run(
        create_fn(
            analysis_type="frequency",
            eigenmodes_count=8,
            frequency_low_hz=2.0,
            frequency_high_hz=200.0,
        )
    )
    assert client.calls[-1] == (
        "analysis",
        {
            "action": "create",
            "analysis_type": "frequency",
            "eigenmodes_count": 8,
            "frequency_low_hz": 2.0,
            "frequency_high_hz": 200.0,
            "solver": "SolverCalculiX",
        },
    )

    asyncio.run(
        create_fn(
            analysis_type="buckling", buckling_factors=3, buckling_accuracy=0.05
        )
    )
    assert client.calls[-1][1]["analysis_type"] == "buckling"
    assert client.calls[-1][1]["buckling_factors"] == 3
    assert client.calls[-1][1]["buckling_accuracy"] == 0.05

    with pytest.raises(ValidationError):
        asyncio.run(create_fn(analysis_type="frequency"))


def test_element_geometry_tool_forwards_fixed_route_and_closed_variants() -> None:
    assert PUBLIC_TOOL_ACTIONS["assign_element_geometry"] == ("element_geometry", "assign")

    client = FakeClient()
    app = create_server(client)
    tools = getattr(getattr(app, "_tool_manager", None), "_tools", None) or getattr(app, "_tools")
    geometry_fn = getattr(tools["assign_element_geometry"], "fn", tools["assign_element_geometry"])

    asyncio.run(
        geometry_fn(
            analysis_id="Analysis",
            kind="shell",
            targets=[{"object_name": "Plate", "subelements": ["Face1"]}],
            thickness_m=0.002,
            offset=0.25,
        )
    )
    assert client.calls[-1] == (
        "element_geometry",
        {
            "action": "assign",
            "analysis_id": "Analysis",
            "kind": "shell",
            "targets": [{"object_name": "Plate", "subelements": ["Face1"]}],
            "thickness_m": 0.002,
            "offset": 0.25,
        },
    )

    asyncio.run(
        geometry_fn(
            analysis_id="Analysis",
            kind="beam_section",
            section_type="rectangular",
            targets=[{"object_name": "Beam", "subelements": ["Edge1"]}],
            rect_width_m=0.02,
            rect_height_m=0.04,
        )
    )
    assert client.calls[-1][0] == "element_geometry"
    assert client.calls[-1][1]["action"] == "assign"
    assert client.calls[-1][1]["section_type"] == "rectangular"
    assert client.calls[-1][1]["rect_width_m"] == 0.02
    assert "offset" not in client.calls[-1][1]

    asyncio.run(
        geometry_fn(
            analysis_id="Analysis",
            kind="beam_rotation",
            targets=[{"object_name": "Beam", "subelements": ["Edge1"]}],
            rotation_rad=1.5,
        )
    )
    assert client.calls[-1][1]["rotation_rad"] == 1.5

    asyncio.run(
        geometry_fn(
            analysis_id="Analysis",
            kind="shell",
            formulation="membrane",
            targets=[{"object_name": "Plate", "subelements": ["Face1"]}],
            thickness_m=0.001,
        )
    )
    assert client.calls[-1][1]["formulation"] == "membrane"

    with pytest.raises(ValidationError):
        asyncio.run(
            geometry_fn(
                analysis_id="Analysis",
                kind="shell",
                targets=[],
                thickness_m=0.002,
            )
        )
    with pytest.raises(ValidationError):
        asyncio.run(
            geometry_fn(
                analysis_id="Analysis",
                kind="beam_section",
                section_type="circular",
                targets=[{"object_name": "Beam", "subelements": ["Face1"]}],
                circ_diameter_m=0.01,
            )
        )


def test_create_mesh_forwards_element_dimension_and_defaults_to_3d() -> None:
    client = FakeClient()
    app = create_server(client)
    tools = getattr(getattr(app, "_tool_manager", None), "_tools", None) or getattr(app, "_tools")
    mesh_fn = getattr(tools["create_mesh"], "fn", tools["create_mesh"])

    asyncio.run(mesh_fn(analysis_id="Analysis", element_dimension="1d"))
    assert client.calls[-1] == (
        "mesh",
        {
            "action": "create",
            "analysis_id": "Analysis",
            "second_order": False,
            "element_dimension": "1d",
        },
    )

    asyncio.run(mesh_fn(analysis_id="Analysis"))
    assert client.calls[-1][1]["element_dimension"] == "3d"


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
            amplitude=[
                {"time_s": 0.0, "scale": 0.0},
                {"time_s": 1.0, "scale": 1.0},
            ],
        )
    )
    remote_fn = getattr(tools["add_remote_load"], "fn", tools["add_remote_load"])
    asyncio.run(
        remote_fn(
            analysis_id="Analysis",
            targets=[{"object_name": "Cantilever", "subelements": ["Face1"]}],
            reference_point_m=[0.0, 0.0, 0.0],
            force_n=[10.0, 0.0, 0.0],
            amplitude=[
                {"time_s": 0.0, "scale": 0.0},
                {"time_s": 1.0, "scale": 1.0},
            ],
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
            amplitude=[
                {"time_s": 0.0, "scale": 0.0},
                {"time_s": 1.0, "scale": 1.0},
            ],
        )
    )
    boundary_fn = getattr(tools["add_boundary_condition"], "fn", tools["add_boundary_condition"])
    asyncio.run(
        boundary_fn(
            analysis_id="Analysis",
            boundary_type="displacement",
            displacement_m=[0.0, 0.0, 0.001],
            amplitude=[
                {"time_s": 0.0, "scale": 0.0},
                {"time_s": 1.0, "scale": 1.0},
            ],
        )
    )

    assert client.calls[0][0] == "load"
    assert client.calls[0][1]["action"] == "add"
    assert client.calls[0][1]["load_type"] == "force"
    assert client.calls[0][1]["force_n"] == 10.0
    assert client.calls[0][1]["amplitude"] == [
        {"time_s": 0.0, "scale": 0.0},
        {"time_s": 1.0, "scale": 1.0},
    ]
    assert PUBLIC_TOOL_ACTIONS["add_remote_load"] == ("remote_load", "add")
    assert client.calls[1][0] == "remote_load"
    assert client.calls[1][1]["action"] == "add"
    assert client.calls[1][1]["reference_point_m"] == [0.0, 0.0, 0.0]
    assert client.calls[1][1]["force_n"] == [10.0, 0.0, 0.0]
    assert client.calls[1][1]["amplitude"] == client.calls[0][1]["amplitude"]
    assert PUBLIC_TOOL_ACTIONS["add_remote_displacement"] == ("remote_displacement", "add")
    assert client.calls[2][0] == "remote_displacement"
    assert client.calls[2][1]["action"] == "add"
    assert client.calls[2][1]["translation_m"] == [0.0, None, None]
    assert client.calls[2][1]["amplitude"] == client.calls[0][1]["amplitude"]
    assert client.calls[3][0] == "boundary_condition"
    assert client.calls[3][1]["action"] == "add"
    assert client.calls[3][1]["boundary_type"] == "displacement"
    assert client.calls[3][1]["amplitude"] == client.calls[0][1]["amplitude"]

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
    amplitude_schema = load_schema["properties"]["amplitude"]["anyOf"][0]
    assert amplitude_schema["minItems"] == 2
    assert amplitude_schema["maxItems"] == 256
    amplitude_point_schema = load_schema["$defs"]["AmplitudePoint"]
    assert amplitude_point_schema["additionalProperties"] is False
    assert amplitude_point_schema["properties"]["time_s"]["minimum"] == 0.0
    assert amplitude_point_schema["properties"]["time_s"]["maximum"] == 1e12
    assert amplitude_point_schema["properties"]["scale"]["minimum"] == -1e9
    assert amplitude_point_schema["properties"]["scale"]["maximum"] == 1e9

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
    assert remote_schema["properties"]["amplitude"]
    assert remote_displacement_schema["properties"]["amplitude"]
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
