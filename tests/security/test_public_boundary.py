"""Adversarial checks for the public MCP/Add-on boundary.

These tests deliberately exercise the typed public requests and then send
hand-written requests directly to the Add-on service.  The latter is the
defence-in-depth check: a caller that bypasses the MCP process must not gain a
second, looser parameter surface.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "addon"))

from freecad_fem_mcp.bridge import BRIDGE_METHODS  # noqa: E402
from freecad_fem_mcp.models import (  # noqa: E402
    AddBoundaryConditionRequest,
    AddConnectionRequest,
    AddLoadRequest,
    AddRemoteLoadRequest,
    AddRemoteDisplacementRequest,
    AssignElementGeometryRequest,
    CreateAnalysisRequest,
    CreateMeshRequest,
    GetResultsRequest,
    PUBLIC_REQUEST_MODELS,
)
from freecad_fem_mcp.server import PUBLIC_TOOL_ACTIONS, TOOL_NAMES  # noqa: E402

from FreeCADFEMMCP.protocol import ALLOWED_METHODS, Request  # noqa: E402
from FreeCADFEMMCP.operations import FreeCADOperations, OperationError  # noqa: E402
from FreeCADFEMMCP.service import FEMService, ServiceError  # noqa: E402


def test_public_requests_are_closed_and_have_no_action_escape_hatch() -> None:
    """Every advertised tool has one fixed action, not a user field."""

    assert set(PUBLIC_REQUEST_MODELS) == set(TOOL_NAMES)
    assert set(PUBLIC_TOOL_ACTIONS) == set(TOOL_NAMES)
    for model in PUBLIC_REQUEST_MODELS.values():
        assert model.model_config.get("extra") == "forbid"
        assert "action" not in model.model_fields
        assert model.model_json_schema().get("additionalProperties") is False

    for tool_name, (method, action) in PUBLIC_TOOL_ACTIONS.items():
        assert method in BRIDGE_METHODS
        assert isinstance(action, str) and action
    assert {method for method, _action in PUBLIC_TOOL_ACTIONS.values()} == set(ALLOWED_METHODS)
    assert PUBLIC_TOOL_ACTIONS["add_remote_load"] == ("remote_load", "add")
    assert "remote_load" in BRIDGE_METHODS
    assert PUBLIC_TOOL_ACTIONS["add_remote_displacement"] == ("remote_displacement", "add")
    assert "remote_displacement" in BRIDGE_METHODS


def test_typed_load_and_boundary_requests_reject_extra_or_nonfinite_values() -> None:
    with pytest.raises(ValidationError):
        AddLoadRequest(analysis_id="A", load_type="force", force_n=1.0, action="add")
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="A",
            load_type="force",
            force_n=1.0,
            pressure_pa=2.0,
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(analysis_id="A", load_type="force", force_n=math.nan)
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="A",
            load_type="gravity",
            acceleration_m_s2=[0.0, 0.0, math.inf],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="A",
            load_type="gravity",
            acceleration_m_s2=[0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="A",
            load_type="gravity",
            acceleration_m_s2=[0.0, 0.0, 0.0],
        )

    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="A",
            boundary_type="fixed",
            displacement_m=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="A",
            boundary_type="displacement",
            displacement_m=[0.0, 0.0, math.nan],
        )
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="A",
            boundary_type="fixed",
            code="__import__('os').system('whoami')",
        )


def test_public_element_geometry_is_closed_discriminated_and_explicit() -> None:
    face = {"object_name": "Plate", "subelements": ["Face1"]}
    edge = {"object_name": "Beam", "subelements": ["Edge1"]}
    shell = AssignElementGeometryRequest(
        analysis_id="A",
        kind="shell",
        targets=[face],
        thickness_m=0.001,
        offset=-1.0,
    )
    assert shell.offset == -1.0
    beam = AssignElementGeometryRequest(
        analysis_id="A",
        kind="beam_section",
        section_type="elliptical",
        targets=[edge],
        axis1_length_m=0.03,
        axis2_length_m=0.02,
    )
    assert beam.axis1_length_m == 0.03
    rotation = AssignElementGeometryRequest(
        analysis_id="A",
        kind="beam_rotation",
        targets=[edge],
        rotation_rad=0.0,
    )
    assert rotation.rotation_rad == 0.0

    bad = (
        {"kind": "shell", "targets": [], "thickness_m": 0.001},
        {
            "kind": "shell",
            "targets": [{"object_name": "Plate", "subelements": []}],
            "thickness_m": 0.001,
        },
        {"kind": "shell", "targets": [edge], "thickness_m": 0.001},
        {"kind": "shell", "targets": [face], "thickness_m": True},
        {"kind": "shell", "targets": [face], "thickness_m": math.nan},
        {"kind": "shell", "targets": [face], "thickness_m": math.inf},
        {"kind": "shell", "targets": [face], "thickness_m": 0.001, "offset": 1.1},
        {
            "kind": "beam_section",
            "section_type": "circular",
            "targets": [edge],
            "circ_diameter_m": 0.01,
            "rect_width_m": 0.01,
        },
        {
            "kind": "beam_section",
            "section_type": "pipe",
            "targets": [edge],
            "pipe_diameter_m": 0.01,
            "pipe_thickness_m": 0.005,
        },
        {"kind": "beam_rotation", "targets": [edge], "rotation_rad": True},
        {"kind": "beam_rotation", "targets": [edge], "rotation_rad": math.inf},
        {
            "kind": "beam_rotation",
            "targets": [edge],
            "rotation_rad": 0.0,
            "native_property": "Rotation",
        },
    )
    for params in bad:
        with pytest.raises(ValidationError):
            AssignElementGeometryRequest(analysis_id="A", **params)

    model_schema = AssignElementGeometryRequest.model_json_schema()
    assert model_schema["additionalProperties"] is False
    assert model_schema["properties"]["kind"]["enum"] == [
        "shell",
        "beam_section",
        "beam_rotation",
    ]


# Amplitudes are deliberately represented as plain mappings at the public
# boundary. The service validates the same shape again before any native
# operation is called; keeping this fixture here makes both checks exercise
# exactly the same contract.
_VALID_AMPLITUDE = [
    {"time_s": 0.0, "scale": 1.0},
    {"time_s": 1.0, "scale": 0.5},
]


def _public_amplitude_cases() -> tuple[tuple[type[object], dict[str, object]], ...]:
    target = {"object_name": "Geometry", "subelements": ["Face1"]}
    return (
        (
            AddLoadRequest,
            {
                "analysis_id": "Analysis",
                "load_type": "force",
                "force_n": 1.0,
            },
        ),
        (
            AddLoadRequest,
            {
                "analysis_id": "Analysis",
                "load_type": "pressure",
                "pressure_pa": 1.0,
            },
        ),
        (
            AddBoundaryConditionRequest,
            {
                "analysis_id": "Analysis",
                "boundary_type": "displacement",
                "displacement_m": [0.0, 0.0, 0.001],
            },
        ),
        (
            AddRemoteLoadRequest,
            {
                "analysis_id": "Analysis",
                "targets": [target],
                "reference_point_m": [0.0, 0.0, 0.0],
                "force_n": [1.0, 0.0, 0.0],
            },
        ),
        (
            AddRemoteDisplacementRequest,
            {
                "analysis_id": "Analysis",
                "targets": [target],
                "reference_point_m": [0.0, 0.0, 0.0],
                "translation_m": [0.001, 0.0, 0.0],
                "rotation_rad": None,
            },
        ),
    )


def test_public_amplitude_is_optional_and_allowed_on_supported_requests() -> None:
    for model_type, params in _public_amplitude_cases():
        model = model_type(**params, amplitude=_VALID_AMPLITUDE)
        assert model.model_dump()["amplitude"] == _VALID_AMPLITUDE

    endpoint_amplitude = [
        {"time_s": 0.0, "scale": -1e9},
        {"time_s": 1e12, "scale": 1e9},
    ]
    model = AddLoadRequest(
        analysis_id="Analysis",
        load_type="force",
        force_n=1.0,
        amplitude=endpoint_amplitude,
    )
    assert model.model_dump()["amplitude"] == endpoint_amplitude

    # Omitting the optional field keeps existing request forms valid.
    for model_type, params in _public_amplitude_cases():
        assert model_type(**params).model_dump().get("amplitude") is None


@pytest.mark.parametrize(
    "label,value",
    [
        ("empty", []),
        ("one_point", [{"time_s": 0.0, "scale": 1.0}]),
        (
            "first_time_not_zero",
            [{"time_s": 0.1, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "duplicate_time",
            [{"time_s": 0.0, "scale": 1.0}, {"time_s": 0.0, "scale": 0.5}],
        ),
        (
            "decreasing_time",
            [{"time_s": 0.0, "scale": 1.0}, {"time_s": 2.0, "scale": 0.5}, {"time_s": 1.0, "scale": 0.5}],
        ),
        (
            "negative_time",
            [{"time_s": -0.1, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_above_limit",
            [{"time_s": 0.0, "scale": 1.0}, {"time_s": 1e12 + 1.0, "scale": 1.0}],
        ),
        (
            "scale_above_limit",
            [{"time_s": 0.0, "scale": 1e9 + 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "scale_below_limit",
            [{"time_s": 0.0, "scale": -1e9 - 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_string",
            [{"time_s": "0.0", "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "scale_string",
            [{"time_s": 0.0, "scale": "1.0"}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_bool",
            [{"time_s": True, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "scale_bool",
            [{"time_s": 0.0, "scale": False}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_nan",
            [{"time_s": math.nan, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "scale_nan",
            [{"time_s": 0.0, "scale": math.nan}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_inf",
            [{"time_s": math.inf, "scale": 1.0}, {"time_s": 2.0, "scale": 1.0}],
        ),
        (
            "scale_inf",
            [{"time_s": 0.0, "scale": math.inf}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "nested_extra",
            [
                {"time_s": 0.0, "scale": 1.0, "metadata": {"source": "x"}},
                {"time_s": 1.0, "scale": 1.0},
            ],
        ),
        (
            "arbitrary_name",
            [
                {"time_s": 0.0, "scale": 1.0, "name": "Ramp"},
                {"time_s": 1.0, "scale": 1.0},
            ],
        ),
        (
            "arbitrary_kind",
            [
                {"time_s": 0.0, "scale": 1.0, "kind": "step"},
                {"time_s": 1.0, "scale": 1.0},
            ],
        ),
        ("wrong_nested_shape", [[0.0, 1.0], [1.0, 1.0]]),
        (
            "too_many_points",
            [{"time_s": float(index), "scale": 1.0} for index in range(257)],
        ),
    ],
)
def test_public_amplitude_rejects_malformed_values(
    label: str, value: list[object]
) -> None:
    del label  # The case label is only for readable pytest failure output.
    for model_type, params in _public_amplitude_cases():
        with pytest.raises(ValidationError):
            model_type(**params, amplitude=value)


@pytest.mark.parametrize(
    "load_type,payload",
    [
        ("gravity", {"acceleration_m_s2": [0.0, -9.81, 0.0]}),
        ("acceleration", {"acceleration_m_s2": [0.0, -9.81, 0.0]}),
        (
            "centrifugal",
            {
                "rotation_frequency_hz": 10.0,
                "axis": {"object_name": "Axis", "subelements": ["Edge1"]},
            },
        ),
    ],
)
def test_public_amplitude_is_rejected_for_unsupported_load_types(
    load_type: str, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type=load_type,
            amplitude=_VALID_AMPLITUDE,
            **payload,
        )

    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="Analysis",
            boundary_type="fixed",
            amplitude=_VALID_AMPLITUDE,
        )


def test_public_create_analysis_accepts_three_closed_analysis_modes() -> None:
    static = CreateAnalysisRequest()
    assert static.analysis_type == "static"

    frequency_without_limits = CreateAnalysisRequest(
        analysis_type="frequency",
        eigenmodes_count=1,
    )
    assert frequency_without_limits.analysis_type == "frequency"

    frequency_at_limits = CreateAnalysisRequest(
        analysis_type="frequency",
        eigenmodes_count=100,
        frequency_low_hz=0.0,
        frequency_high_hz=1e9,
    )
    assert frequency_at_limits.frequency_high_hz == 1e9

    buckling = CreateAnalysisRequest(
        analysis_type="buckling",
        buckling_factors=100,
        buckling_accuracy=1.0,
    )
    assert buckling.buckling_factors == 100


@pytest.mark.parametrize(
    "params",
    [
        {"analysis_type": "frequency"},
        {"analysis_type": "frequency", "eigenmodes_count": 1, "frequency_low_hz": 0.0},
        {"analysis_type": "frequency", "eigenmodes_count": 1, "frequency_high_hz": 1.0},
        {
            "analysis_type": "frequency",
            "eigenmodes_count": 1,
            "frequency_low_hz": 10.0,
            "frequency_high_hz": 10.0,
        },
        {
            "analysis_type": "frequency",
            "eigenmodes_count": 1,
            "frequency_low_hz": 11.0,
            "frequency_high_hz": 10.0,
        },
        {"analysis_type": "buckling"},
        {"analysis_type": "buckling", "buckling_factors": 1},
        {"analysis_type": "buckling", "buckling_accuracy": 0.1},
        {
            "analysis_type": "static",
            "eigenmodes_count": 1,
            "frequency_low_hz": 0.0,
            "frequency_high_hz": 1.0,
            "buckling_factors": 1,
            "buckling_accuracy": 0.1,
        },
        {
            "analysis_type": "frequency",
            "eigenmodes_count": 1,
            "buckling_factors": 1,
            "buckling_accuracy": 0.1,
        },
        {
            "analysis_type": "buckling",
            "buckling_factors": 1,
            "buckling_accuracy": 0.1,
            "eigenmodes_count": 1,
        },
        {"analysis_type": "modal"},
        {"analysis_type": True},
        {"analysis_type": "static", "action": "__import__('os').system('whoami')"},
        {"analysis_type": "static", "code": "exec(1)"},
    ],
)
def test_public_create_analysis_rejects_missing_modes_and_unrelated_fields(
    params: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(**params)


@pytest.mark.parametrize(
    "field,value",
    [
        ("eigenmodes_count", 0),
        ("eigenmodes_count", 101),
        ("eigenmodes_count", -1),
        ("eigenmodes_count", True),
        ("eigenmodes_count", 1.0),
        ("eigenmodes_count", "10"),
        ("frequency_low_hz", -0.1),
        ("frequency_low_hz", 1e9 + 0.1),
        ("frequency_low_hz", True),
        ("frequency_low_hz", "1 Hz"),
        ("frequency_low_hz", math.nan),
        ("frequency_low_hz", math.inf),
        ("frequency_high_hz", -0.1),
        ("frequency_high_hz", 1e9 + 0.1),
        ("frequency_high_hz", False),
        ("frequency_high_hz", "1 Hz"),
        ("frequency_high_hz", math.nan),
        ("frequency_high_hz", math.inf),
        ("buckling_factors", 0),
        ("buckling_factors", 101),
        ("buckling_factors", -1),
        ("buckling_factors", False),
        ("buckling_factors", 1.0),
        ("buckling_factors", "10"),
        ("buckling_accuracy", 0.0),
        ("buckling_accuracy", -0.1),
        ("buckling_accuracy", 1.1),
        ("buckling_accuracy", True),
        ("buckling_accuracy", "0.1"),
        ("buckling_accuracy", math.nan),
        ("buckling_accuracy", math.inf),
    ],
)
def test_public_create_analysis_rejects_bad_numeric_fields(field: str, value: object) -> None:
    if field.startswith("eigen"):
        params: dict[str, object] = {"analysis_type": "frequency", "eigenmodes_count": 1}
    elif field.startswith("frequency"):
        params = {
            "analysis_type": "frequency",
            "eigenmodes_count": 1,
            "frequency_low_hz": 0.0,
            "frequency_high_hz": 1.0,
        }
    else:
        params = {
            "analysis_type": "buckling",
            "buckling_factors": 1,
            "buckling_accuracy": 0.1,
        }
    params[field] = value
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(**params)


_CONNECTION_SLAVE = {"object_name": "Upper", "subelements": ["Face3"]}
_CONNECTION_MASTER = {"object_name": "Lower", "subelements": ["Face7"]}


def _public_tie_params() -> dict[str, object]:
    return {
        "analysis_id": "Analysis",
        "connection_type": "tie",
        "slave": _CONNECTION_SLAVE,
        "master": _CONNECTION_MASTER,
        "tolerance_m": 0.0,
        "adjust": False,
    }


def _public_contact_params() -> dict[str, object]:
    return {
        "analysis_id": "Analysis",
        "connection_type": "contact",
        "slave": _CONNECTION_SLAVE,
        "master": _CONNECTION_MASTER,
        "surface_behavior": "hard",
    }


def _public_linear_contact_params() -> dict[str, object]:
    return {
        **_public_contact_params(),
        "surface_behavior": "linear",
        "normal_stiffness_pa_per_m": 1.0e9,
        "friction": True,
        "friction_coefficient": 0.25,
        "stick_stiffness_pa_per_m": 3.0e9,
        "adjust_m": 0.004,
    }


def test_public_connection_accepts_closed_tie_and_contact_variants() -> None:
    tie = AddConnectionRequest(**_public_tie_params())
    assert tie.tolerance_m == 0.0
    assert tie.adjust is False

    contact = AddConnectionRequest(**_public_contact_params())
    assert contact.surface_behavior == "hard"

    linear = AddConnectionRequest(**_public_linear_contact_params())
    assert linear.normal_stiffness_pa_per_m == 1.0e9
    assert linear.friction is True

    endpoint_tie = AddConnectionRequest(
        **{**_public_tie_params(), "tolerance_m": 1e6, "adjust": True}
    )
    assert endpoint_tie.tolerance_m == 1e6


@pytest.mark.parametrize(
    "params",
    [
        {"connection_type": "tie"},
        {
            **_public_tie_params(),
            "tolerance_m": None,
        },
        {
            **_public_tie_params(),
            "adjust": None,
        },
        {
            **_public_tie_params(),
            "surface_behavior": "hard",
        },
        {
            **_public_contact_params(),
            "tolerance_m": 0.1,
        },
        {
            **_public_contact_params(),
            "adjust": False,
        },
        {
            **_public_contact_params(),
            "surface_behavior": "linear",
        },
        {
            **_public_contact_params(),
            "surface_behavior": "tied",
        },
        {
            **_public_contact_params(),
            "surface_behavior": True,
        },
        {
            **_public_tie_params(),
            "connection_type": "bonded",
        },
        {
            **_public_tie_params(),
            "connection_type": True,
        },
        {
            **_public_tie_params(),
            "action": "__import__('os').system('whoami')",
        },
        {
            **_public_contact_params(),
            "friction_coefficient": 0.2,
        },
        {
            **_public_contact_params(),
            "slope": 1.0,
        },
        {
            **_public_contact_params(),
            "thermal_conductance": [1.0],
        },
        {
            **_public_contact_params(),
            "parameters": {"surface_behavior": "hard"},
        },
        {
            **_public_contact_params(),
            "kind": "contact",
        },
    ],
)
def test_public_connection_rejects_variant_confusion_and_extra_fields(
    params: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AddConnectionRequest(**params)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tolerance_m", -0.1),
        ("tolerance_m", 1e6 + 0.1),
        ("tolerance_m", True),
        ("tolerance_m", "1 m"),
        ("tolerance_m", math.nan),
        ("tolerance_m", math.inf),
        ("adjust", 0),
        ("adjust", 1),
        ("adjust", "false"),
        ("adjust", math.nan),
    ],
)
def test_public_tie_rejects_bad_tolerance_and_adjust(field: str, value: object) -> None:
    params = _public_tie_params()
    params[field] = value
    with pytest.raises(ValidationError):
        AddConnectionRequest(**params)


@pytest.mark.parametrize(
    "field,value",
    [
        ("adjust_m", -0.1),
        ("adjust_m", 1e6 + 0.1),
        ("adjust_m", True),
        ("adjust_m", math.nan),
        ("normal_stiffness_pa_per_m", 0.0),
        ("normal_stiffness_pa_per_m", 1e15 + 1.0),
        ("friction_coefficient", 0.0),
        ("friction_coefficient", 10.1),
        ("stick_stiffness_pa_per_m", 0.0),
        ("stick_stiffness_pa_per_m", 1e15 + 1.0),
    ],
)
def test_public_contact_rejects_bad_native_ranges(field: str, value: object) -> None:
    params = _public_linear_contact_params()
    params[field] = value
    with pytest.raises(ValidationError):
        AddConnectionRequest(**params)


@pytest.mark.parametrize(
    "field,value",
    [
        ("slave", {"object_name": "Upper", "subelements": []}),
        ("slave", {"object_name": "Upper", "subelements": ["Face1", "Face2"]}),
        ("slave", {"object_name": "Upper", "subelements": ["Edge1"]}),
        ("slave", {"object_name": "Upper", "subelements": ["Face0"]}),
        ("slave", {"object_name": "Upper", "subelements": ["face1"]}),
        ("slave", {"object_name": "Upper", "subelements": "Face1"}),
        ("slave", {"object_name": "Upper", "subelements": ["Face1"], "kind": "Face"}),
        ("master", {"object_name": "Lower", "subelements": []}),
        ("master", {"object_name": "Lower", "subelements": ["Vertex1"]}),
        ("master", {"object_name": "Lower", "subelements": ["Face0"]}),
        ("master", {"object_name": "Lower", "subelements": ["Face1", "Face2"]}),
    ],
)
def test_public_connection_requires_one_face_per_side(field: str, value: object) -> None:
    params = _public_tie_params()
    params[field] = value
    with pytest.raises(ValidationError):
        AddConnectionRequest(**params)


def test_public_connection_rejects_same_slave_and_master_face() -> None:
    params = _public_tie_params()
    params["master"] = {"object_name": "Upper", "subelements": ["Face3"]}
    with pytest.raises(ValidationError):
        AddConnectionRequest(**params)


def test_public_numeric_limits_remain_bounded() -> None:
    with pytest.raises(ValidationError):
        CreateMeshRequest(analysis_id="A", element_size_mm=math.inf)
    with pytest.raises(ValidationError):
        CreateMeshRequest(analysis_id="A", element_size_mm=0.0)
    with pytest.raises(ValidationError):
        GetResultsRequest(analysis_id="A", max_items=10001)
    with pytest.raises(ValidationError):
        GetResultsRequest(analysis_id="A", max_items=0)
    with pytest.raises(ValidationError):
        CreateMeshRequest(analysis_id="A" * 257)


def test_remote_load_public_request_is_closed_and_mode_specific() -> None:
    target = {"object_name": "Geometry", "subelements": ["Face1"]}
    valid = AddRemoteLoadRequest(
        analysis_id="Analysis",
        targets=[target],
        reference_point_m=[0.0, 0.0, 0.0],
        force_n=[1.0, 0.0, 0.0],
    )
    assert valid.force_n == [1.0, 0.0, 0.0]
    both = AddRemoteLoadRequest(
        analysis_id="Analysis",
        targets=[target],
        reference_point_m=[1e9, -1e9, 0.0],
        force_n=[1e15, 0.0, 0.0],
        moment_n_m=[0.0, -1e15, 0.0],
    )
    assert both.moment_n_m == [0.0, -1e15, 0.0]

    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            analysis_id="Analysis",
            targets=[target],
            reference_point_m=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            analysis_id="Analysis",
            targets=[target],
            reference_point_m=[0.0, 0.0, 0.0],
            force_n=[0.0, 0.0, 0.0],
            moment_n_m=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            analysis_id="Analysis",
            targets=[target],
            reference_point_m=[0.0, 0.0, 0.0],
            force_n=[1.0, 0.0, 0.0],
            code="exec(1)",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("reference_point_m", [1_000_000_000.1, 0.0, 0.0]),
        ("reference_point_m", [float("nan"), 0.0, 0.0]),
        ("reference_point_m", [float("inf"), 0.0, 0.0]),
        ("reference_point_m", [True, 0.0, 0.0]),
        ("reference_point_m", ["1 m", 0.0, 0.0]),
        ("reference_point_m", [0.0, 0.0]),
        ("reference_point_m", [0.0, 0.0, 0.0, 0.0]),
        ("force_n", [1_000_000_000_000_000.1, 0.0, 0.0]),
        ("force_n", [float("nan"), 0.0, 0.0]),
        ("force_n", [True, 0.0, 0.0]),
        ("force_n", ["1 N", 0.0, 0.0]),
        ("force_n", [0.0, 0.0]),
        ("moment_n_m", [1_000_000_000_000_000.1, 0.0, 0.0]),
        ("moment_n_m", [float("inf"), 0.0, 0.0]),
        ("moment_n_m", [0.0, False, 0.0]),
        ("moment_n_m", ["1 N*m", 0.0, 0.0]),
        ("moment_n_m", [0.0, 0.0, 0.0, 0.0]),
        ("force_n", []),
        ("moment_n_m", []),
    ],
)
def test_remote_load_public_model_rejects_nonfinite_coercion_and_bounds(
    field: str, value: list[object]
) -> None:
    target = {"object_name": "Geometry", "subelements": ["Face1"]}
    params: dict[str, object] = {
        "analysis_id": "Analysis",
        "targets": [target],
        "reference_point_m": [0.0, 0.0, 0.0],
        "force_n": [1.0, 0.0, 0.0],
    }
    params[field] = value
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(**params)


def test_remote_load_public_model_rejects_empty_targets_and_nested_extras() -> None:
    base = {
        "analysis_id": "Analysis",
        "reference_point_m": [0.0, 0.0, 0.0],
        "force_n": [1.0, 0.0, 0.0],
    }
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(**base, targets=[])
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            **base,
            targets=[
                {
                    "object_name": "Geometry",
                    "subelements": ["Face1"],
                    "property": "Force",
                }
            ],
        )


def test_remote_displacement_public_model_uses_global_strict_vectors() -> None:
    target = {"object_name": "Geometry", "subelements": ["Face1"]}
    translation = AddRemoteDisplacementRequest(
        analysis_id="Analysis",
        targets=[target],
        reference_point_m=[0.0, 0.0, 0.0],
        translation_m=[0.001, 0.0, 0.0],
        rotation_rad=None,
    )
    assert translation.translation_m == [0.001, 0.0, 0.0]

    rotation = AddRemoteDisplacementRequest(
        analysis_id="Analysis",
        targets=[target],
        reference_point_m=[1e9, -1e9, 0.0],
        translation_m=None,
        rotation_rad=[0.0, 0.5, 0.0],
    )
    assert rotation.rotation_rad == [0.0, 0.5, 0.0]

    # A numeric zero is an explicit constrained DOF; None means Free.  Both
    # vectors may therefore be present and all-zero as long as they are not
    # omitted altogether.
    constrained = AddRemoteDisplacementRequest(
        analysis_id="Analysis",
        targets=[target],
        reference_point_m=[0.0, 0.0, 0.0],
        translation_m=[0.0, 0.0, 0.0],
        rotation_rad=[0.0, 0.0, 0.0],
    )
    assert constrained.translation_m == [0.0, 0.0, 0.0]

    partially_free = AddRemoteDisplacementRequest(
        analysis_id="Analysis",
        targets=[target],
        reference_point_m=[0.0, 0.0, 0.0],
        translation_m=[None, 0.001, None],
        rotation_rad=[None, None, None],
    )
    assert partially_free.translation_m == [None, 0.001, None]

    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(
            analysis_id="Analysis",
            targets=[target],
            reference_point_m=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(
            analysis_id="Analysis",
            targets=[target],
            reference_point_m=[0.0, 0.0, 0.0],
            translation_m=[1.0, 0.0, 0.0],
            rotation_rad=[0.0, 0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(
            analysis_id="Analysis",
            targets=[target],
            reference_point_m=[0.0, 0.0, 0.0],
            translation_m=[1.0, 0.0, 0.0],
            rotation_rad=[0.0, 0.0, 0.0],
            coordinate_system="global",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("reference_point_m", [1_000_000_000.1, 0.0, 0.0]),
        ("reference_point_m", [float("nan"), 0.0, 0.0]),
        ("reference_point_m", [float("inf"), 0.0, 0.0]),
        ("reference_point_m", [True, 0.0, 0.0]),
        ("reference_point_m", ["1 m", 0.0, 0.0]),
        ("reference_point_m", [0.0, 0.0]),
        ("reference_point_m", [0.0, 0.0, 0.0, 0.0]),
        ("translation_m", [1_000_000_000.1, 0.0, 0.0]),
        ("translation_m", [float("nan"), 0.0, 0.0]),
        ("translation_m", [True, 0.0, 0.0]),
        ("translation_m", ["1 m", 0.0, 0.0]),
        ("translation_m", [0.0, 0.0]),
        ("rotation_rad", [1_000_000.1, 0.0, 0.0]),
        ("rotation_rad", [float("inf"), 0.0, 0.0]),
        ("rotation_rad", [False, 0.0, 0.0]),
        ("rotation_rad", ["1 deg", 0.0, 0.0]),
        ("rotation_rad", [0.0, 0.0, 0.0, 0.0]),
    ],
)
def test_remote_displacement_public_model_rejects_bad_vectors(
    field: str, value: list[object]
) -> None:
    target = {"object_name": "Geometry", "subelements": ["Face1"]}
    params: dict[str, object] = {
        "analysis_id": "Analysis",
        "targets": [target],
        "reference_point_m": [0.0, 0.0, 0.0],
        "translation_m": [0.001, 0.0, 0.0],
        "rotation_rad": None,
    }
    params[field] = value
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(**params)


def test_remote_displacement_public_model_rejects_target_and_generic_extras() -> None:
    base = {
        "analysis_id": "Analysis",
        "targets": [{"object_name": "Geometry", "subelements": ["Face1"]}],
        "reference_point_m": [0.0, 0.0, 0.0],
        "translation_m": [0.001, 0.0, 0.0],
    }
    empty_targets = dict(base)
    empty_targets["targets"] = []
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(**empty_targets)
    extra_target = dict(base)
    extra_target["targets"] = [
        {
            "object_name": "Geometry",
            "subelements": ["Face1"],
            "property": "ReferenceNode",
        }
    ]
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(**extra_target)
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(**base, code="eval('x')")


class _SecurityShapeElement:
    def __init__(self, shape_type: str, curve_type: str | None = None) -> None:
        self.ShapeType = shape_type
        if curve_type is not None:
            self.Curve = type("Curve", (), {"TypeId": curve_type})()


class _SecurityShape:
    def __init__(self, *, linear_axis: bool = True) -> None:
        curve_type = "Part::GeomLine" if linear_axis else "Part::GeomCircle"
        self._elements = {
            "Vertex1": _SecurityShapeElement("Vertex"),
            "Edge1": _SecurityShapeElement("Edge", curve_type),
            "Face1": _SecurityShapeElement("Face"),
            "Solid1": _SecurityShapeElement("Solid"),
        }
        self.Solids = [self._elements["Solid1"]]

    def getElement(self, name: str) -> _SecurityShapeElement:
        if name not in self._elements:
            raise ValueError("subelement does not exist")
        return self._elements[name]


class _SecurityMismatchedShape(_SecurityShape):
    def getElement(self, name: str) -> _SecurityShapeElement:
        if name == "Face1":
            return _SecurityShapeElement("Edge")
        return super().getElement(name)


class _SecurityShapeObject:
    def __init__(self, shape: _SecurityShape | None = None) -> None:
        self.Shape = shape or _SecurityShape()


def test_addon_native_remote_revalidation_requires_actual_same_kind_shapes() -> None:
    obj = _SecurityShapeObject()
    for kind in ("Vertex1", "Edge1", "Face1"):
        FreeCADOperations._validate_remote_references([(obj, kind)])

    for stale in ("Vertex999", "Edge999", "Face999", "Solid1"):
        with pytest.raises(OperationError):
            FreeCADOperations._validate_remote_references([(obj, stale)])
    with pytest.raises(OperationError):
        FreeCADOperations._validate_remote_references([(obj, "Face1"), (obj, "Edge1")])


def test_addon_native_centrifugal_revalidation_requires_linear_axis_and_solids() -> None:
    obj = _SecurityShapeObject()
    FreeCADOperations._validate_centrifugal_axis([(obj, "Edge1")])
    FreeCADOperations._validate_centrifugal_bodies([])  # [] means all solids.
    FreeCADOperations._validate_centrifugal_bodies([(obj, "Solid1")])

    for stale_axis in ("Edge999", "Face1", "Vertex1"):
        with pytest.raises(OperationError):
            FreeCADOperations._validate_centrifugal_axis([(obj, stale_axis)])
    with pytest.raises(OperationError):
        FreeCADOperations._validate_centrifugal_axis(
            [(_SecurityShapeObject(_SecurityShape(linear_axis=False)), "Edge1")]
        )
    for invalid_target in ("Solid999", "Face1", "Edge1"):
        with pytest.raises(OperationError):
            FreeCADOperations._validate_centrifugal_bodies([(obj, invalid_target)])


class _ConnectionNative:
    def __init__(self, name: str, type_id: str) -> None:
        self.Name = name
        self.Label = name
        self.TypeId = type_id
        self.References: list[tuple[object, str]] = []
        self.Tolerance = 0.0
        self.Adjust = False
        self.CyclicSymmetry = False
        self.SurfaceBehavior = "Hard"
        self.Friction = False
        self.EnableThermalContact = False


class _ConnectionObjectsFem:
    @staticmethod
    def makeConstraintTie(_doc: object, name: str) -> _ConnectionNative:
        return _ConnectionNative(name, "Fem::ConstraintTie")

    @staticmethod
    def makeConstraintContact(_doc: object, name: str) -> _ConnectionNative:
        return _ConnectionNative(name, "Fem::ConstraintContact")


class _ConnectionSolver:
    Name = "SolverCalculiX"
    Label = "SolverCalculiX"
    TypeId = "Fem::SolverCalculiX"
    AnalysisType = "static"


class _ConnectionAnalysis:
    Name = "Analysis"
    Label = "Analysis"
    TypeId = "Fem::FemAnalysis"

    def __init__(self) -> None:
        self.Group: list[object] = [_ConnectionSolver()]

    def addObject(self, obj: object) -> None:
        self.Group.append(obj)


class _ConnectionDocument:
    Name = "Doc"

    def __init__(self) -> None:
        self.analysis = _ConnectionAnalysis()
        self.upper = _SecurityShapeObject(_SecurityShape())
        self.upper.Name = self.upper.Label = "Upper"
        self.lower = _SecurityShapeObject(_SecurityShape())
        self.lower.Name = self.lower.Label = "Lower"
        self.Objects = [self.analysis, self.upper, self.lower]
        self._objects = {
            "Analysis": self.analysis,
            "Upper": self.upper,
            "Lower": self.lower,
        }

    def getObject(self, name: str) -> object | None:
        return self._objects.get(name)

    def openTransaction(self, _label: str) -> None:
        return None

    def commitTransaction(self) -> None:
        return None

    def abortTransaction(self) -> None:
        return None


class _ConnectionApp:
    def __init__(self) -> None:
        self.ActiveDocument = _ConnectionDocument()

    @staticmethod
    def Version() -> tuple[str, str, str]:
        return ("1", "1", "3")


def _connection_native_params(kind: str = "tie") -> dict[str, object]:
    params: dict[str, object] = {
        "references": [
            {"object": "Upper", "sub_element": "Face1"},
            {"object": "Lower", "sub_element": "Face1"},
        ],
    }
    if kind == "tie":
        params.update({"tolerance_m": 0.001, "adjust": True})
    else:
        params.update({"surface_behavior": "hard"})
    return params


@pytest.mark.parametrize("kind", ("tie", "contact"))
def test_addon_native_connection_revalidates_live_faces_and_preserves_group(
    kind: str,
) -> None:
    app = _ConnectionApp()
    operations = FreeCADOperations(app=app, objects_fem=_ConnectionObjectsFem)
    analysis = app.ActiveDocument.analysis
    before = list(analysis.Group)

    result = operations.add_connection("Analysis", kind, _connection_native_params(kind))

    assert result["kind"] == kind
    assert len(analysis.Group) == len(before) + 1
    native = analysis.Group[-1]
    assert native.References == [
        (app.ActiveDocument.upper, "Face1"),
        (app.ActiveDocument.lower, "Face1"),
    ]

    invalid_cases = (
        ("stale FaceN", "Upper", "Face999"),
        ("wrong subshape kind", "Upper", "Edge1"),
    )
    for _label, object_name, sub_element in invalid_cases:
        params = _connection_native_params(kind)
        params["references"] = [
            {"object": object_name, "sub_element": sub_element},
            {"object": "Lower", "sub_element": "Face1"},
        ]
        group_before = list(analysis.Group)
        with pytest.raises(OperationError):
            operations.add_connection("Analysis", kind, params)
        assert analysis.Group == group_before

    wrong_shape = _SecurityShapeObject(_SecurityMismatchedShape())
    wrong_shape.Name = wrong_shape.Label = "Upper"
    app.ActiveDocument._objects["Upper"] = wrong_shape
    app.ActiveDocument.Objects[1] = wrong_shape
    group_before = list(analysis.Group)
    with pytest.raises(OperationError):
        operations.add_connection("Analysis", kind, _connection_native_params(kind))
    assert analysis.Group == group_before


class _RecordingOperations:
    app = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.analysis_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.connection_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.remote_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.remote_displacement_calls: list[
            tuple[tuple[object, ...], dict[str, object]]
        ] = []
        self.centrifugal_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.geometry_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def add_constraint(self, analysis_id: str, kind: str, data: dict[str, object]) -> dict[str, str]:
        self.calls.append((analysis_id, kind, data))
        return {"name": "Constraint"}

    def create_analysis(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.analysis_calls.append((args, kwargs))
        name = kwargs.get("name")
        if name is None and args:
            name = args[0]
        return {
            "name": name or "Analysis",
            "analysis_type": kwargs.get("analysis_type", "static"),
        }

    def add_connection(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.connection_calls.append((args, kwargs))
        return {"name": "Connection"}

    def add_remote_load(self, *args: object, **kwargs: object) -> dict[str, str]:
        self.remote_calls.append((args, kwargs))
        return {"name": "RemoteLoad"}

    def add_remote_displacement(self, *args: object, **kwargs: object) -> dict[str, str]:
        self.remote_displacement_calls.append((args, kwargs))
        return {"name": "RemoteDisplacement"}

    def add_centrifugal_load(self, *args: object, **kwargs: object) -> dict[str, str]:
        self.centrifugal_calls.append((args, kwargs))
        return {"name": "Centrifugal"}

    def assign_element_geometry(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.geometry_calls.append((args, kwargs))
        return {"name": "ElementGeometry", "kind": args[1] if len(args) > 1 else None}


class _EmptySelection:
    gui = None

    @staticmethod
    def capture() -> dict[str, list[object]]:
        return {"items": []}


def _service() -> tuple[FEMService, _RecordingOperations]:
    operations = _RecordingOperations()
    # Jobs and pipeline are not reached by these routes.  Supplying inert
    # objects prevents the test from importing or contacting FreeCAD.
    service = FEMService(
        operations=operations,
        selection=_EmptySelection(),
        jobs=object(),
        pipeline=object(),
    )
    return service, operations


def _addon_analysis_params(analysis_type: str) -> dict[str, object]:
    params: dict[str, object] = {
        "action": "create",
        "analysis_type": analysis_type,
        "solver": "SolverCalculiX",
    }
    if analysis_type == "frequency":
        params.update(
            {
                "eigenmodes_count": 10,
                "frequency_low_hz": 0.0,
                "frequency_high_hz": 1e9,
            }
        )
    elif analysis_type == "buckling":
        params.update({"buckling_factors": 10, "buckling_accuracy": 0.01})
    return params


def _analysis_call_payload(call: tuple[tuple[object, ...], dict[str, object]]) -> dict[str, object]:
    args, kwargs = call
    payload = dict(kwargs)
    if args:
        payload.setdefault("name", args[0])
    if len(args) > 1:
        payload.setdefault("analysis_type", args[1])
    return payload


def test_addon_accepts_three_analysis_modes_and_forwards_typed_values() -> None:
    service, operations = _service()
    for request_id, analysis_type in enumerate(("static", "frequency", "buckling"), start=500):
        params = _addon_analysis_params(analysis_type)
        before = len(operations.analysis_calls)
        result = service(Request(request_id, "analysis", params))
        assert result["analysis_id"] == "Analysis"
        assert len(operations.analysis_calls) == before + 1
        forwarded = _analysis_call_payload(operations.analysis_calls[-1])
        assert forwarded.get("analysis_type", "static") == analysis_type
        if analysis_type == "frequency":
            assert forwarded.get("eigenmodes_count") == 10
            assert forwarded.get("frequency_low_hz") == 0.0
            assert forwarded.get("frequency_high_hz") == 1e9
        elif analysis_type == "buckling":
            assert forwarded.get("buckling_factors") == 10
            assert forwarded.get("buckling_accuracy") == 0.01


@pytest.mark.parametrize(
    "params",
    [
        {"action": "create", "analysis_type": "frequency"},
        {
            "action": "create",
            "analysis_type": "frequency",
            "eigenmodes_count": 1,
            "frequency_low_hz": 0.0,
        },
        {
            "action": "create",
            "analysis_type": "frequency",
            "eigenmodes_count": 1,
            "frequency_high_hz": 1.0,
        },
        {
            "action": "create",
            "analysis_type": "frequency",
            "eigenmodes_count": 1,
            "frequency_low_hz": 10.0,
            "frequency_high_hz": 10.0,
        },
        {
            "action": "create",
            "analysis_type": "frequency",
            "eigenmodes_count": 1,
            "frequency_low_hz": 11.0,
            "frequency_high_hz": 10.0,
        },
        {"action": "create", "analysis_type": "buckling"},
        {
            "action": "create",
            "analysis_type": "buckling",
            "buckling_factors": 1,
        },
        {
            "action": "create",
            "analysis_type": "buckling",
            "buckling_accuracy": 0.1,
        },
        {
            "action": "create",
            "analysis_type": "static",
            "eigenmodes_count": 1,
        },
        {
            "action": "create",
            "analysis_type": "frequency",
            "eigenmodes_count": 1,
            "buckling_factors": 1,
            "buckling_accuracy": 0.1,
        },
        {
            "action": "create",
            "analysis_type": "buckling",
            "buckling_factors": 1,
            "buckling_accuracy": 0.1,
            "eigenmodes_count": 1,
        },
        {"action": "create", "analysis_type": "modal"},
        {"action": "create", "analysis_type": True},
        {"action": "create", "analysis_type": "static", "action_name": "create"},
        {"action": "__import__", "analysis_type": "static"},
        {"action": "create", "analysis_type": "static", "code": "exec(1)"},
    ],
)
def test_addon_rejects_bad_analysis_requests_before_dispatch(
    params: dict[str, object],
) -> None:
    service, operations = _service()
    before = len(operations.analysis_calls)
    with pytest.raises(ServiceError):
        service(Request(550, "analysis", params))
    assert len(operations.analysis_calls) == before


@pytest.mark.parametrize(
    "field,value,analysis_type",
    [
        ("eigenmodes_count", 0, "frequency"),
        ("eigenmodes_count", 101, "frequency"),
        ("eigenmodes_count", -1, "frequency"),
        ("eigenmodes_count", True, "frequency"),
        ("eigenmodes_count", 1.0, "frequency"),
        ("eigenmodes_count", "10", "frequency"),
        ("frequency_low_hz", -0.1, "frequency"),
        ("frequency_low_hz", 1e9 + 0.1, "frequency"),
        ("frequency_low_hz", True, "frequency"),
        ("frequency_low_hz", "1 Hz", "frequency"),
        ("frequency_low_hz", math.nan, "frequency"),
        ("frequency_low_hz", math.inf, "frequency"),
        ("frequency_high_hz", -0.1, "frequency"),
        ("frequency_high_hz", 1e9 + 0.1, "frequency"),
        ("frequency_high_hz", False, "frequency"),
        ("frequency_high_hz", "1 Hz", "frequency"),
        ("frequency_high_hz", math.nan, "frequency"),
        ("frequency_high_hz", math.inf, "frequency"),
        ("buckling_factors", 0, "buckling"),
        ("buckling_factors", 101, "buckling"),
        ("buckling_factors", -1, "buckling"),
        ("buckling_factors", False, "buckling"),
        ("buckling_factors", 1.0, "buckling"),
        ("buckling_factors", "10", "buckling"),
        ("buckling_accuracy", 0.0, "buckling"),
        ("buckling_accuracy", -0.1, "buckling"),
        ("buckling_accuracy", 1.1, "buckling"),
        ("buckling_accuracy", True, "buckling"),
        ("buckling_accuracy", "0.1", "buckling"),
        ("buckling_accuracy", math.nan, "buckling"),
        ("buckling_accuracy", math.inf, "buckling"),
    ],
)
def test_addon_rejects_bad_analysis_numeric_fields_before_dispatch(
    field: str, value: object, analysis_type: str,
) -> None:
    service, operations = _service()
    params = _addon_analysis_params(analysis_type)
    params[field] = value
    before = len(operations.analysis_calls)
    with pytest.raises(ServiceError):
        service(Request(600, "analysis", params))
    assert len(operations.analysis_calls) == before


def _addon_tie_params() -> dict[str, object]:
    return {
        "action": "add",
        "analysis_id": "Analysis",
        "connection_type": "tie",
        "slave": _CONNECTION_SLAVE,
        "master": _CONNECTION_MASTER,
        "tolerance_m": 0.0,
        "adjust": False,
    }


def _addon_contact_params() -> dict[str, object]:
    return {
        "action": "add",
        "analysis_id": "Analysis",
        "connection_type": "contact",
        "slave": _CONNECTION_SLAVE,
        "master": _CONNECTION_MASTER,
        "surface_behavior": "hard",
    }


def _addon_linear_contact_params() -> dict[str, object]:
    return {
        **_addon_contact_params(),
        "surface_behavior": "linear",
        "normal_stiffness_pa_per_m": 1.0e9,
        "friction": True,
        "friction_coefficient": 0.25,
        "stick_stiffness_pa_per_m": 3.0e9,
        "adjust_m": 0.004,
    }


def test_addon_accepts_tie_and_contact_and_forwards_closed_payload() -> None:
    service, operations = _service()
    for request_id, params in enumerate(
        (_addon_tie_params(), _addon_contact_params(), _addon_linear_contact_params()),
        start=650,
    ):
        before = len(operations.connection_calls)
        result = service(Request(request_id, "connection", params))
        assert result["connection_id"] == "Connection"
        assert len(operations.connection_calls) == before + 1
        args, kwargs = operations.connection_calls[-1]
        assert kwargs == {}
        assert len(args) == 3
        assert args[0] == params["analysis_id"]
        assert args[1] == params["connection_type"]
        assert isinstance(args[2], dict)
        expected: dict[str, object] = {
            "references": [
                {"object": "Upper", "sub_element": "Face3"},
                {"object": "Lower", "sub_element": "Face7"},
            ],
        }
        if params["connection_type"] == "tie":
            expected.update({"tolerance_m": 0.0, "adjust": False})
        else:
            expected["surface_behavior"] = params["surface_behavior"]
            for field in (
                "friction",
                "friction_coefficient",
                "normal_stiffness_pa_per_m",
                "stick_stiffness_pa_per_m",
                "adjust_m",
            ):
                if field in params:
                    expected[field] = params[field]
        assert args[2] == expected


@pytest.mark.parametrize(
    "params",
    [
        {"action": "add", "analysis_id": "Analysis", "connection_type": "tie"},
        {
            **_addon_tie_params(),
            "tolerance_m": None,
        },
        {
            **_addon_tie_params(),
            "adjust": None,
        },
        {
            **_addon_tie_params(),
            "surface_behavior": "hard",
        },
        {
            **_addon_tie_params(),
            "friction": False,
        },
        {
            **_addon_contact_params(),
            "tolerance_m": 0.1,
        },
        {
            **_addon_contact_params(),
            "adjust": False,
        },
        {
            **_addon_contact_params(),
            "surface_behavior": "linear",
        },
        {
            **_addon_contact_params(),
            "surface_behavior": True,
        },
        {
            **_addon_tie_params(),
            "connection_type": "bonded",
        },
        {
            **_addon_tie_params(),
            "connection_type": True,
        },
        {
            **_addon_tie_params(),
            "code": "exec(1)",
        },
        {
            **_addon_contact_params(),
            "friction_coefficient": 0.2,
        },
        {
            **_addon_contact_params(),
            "slope": 1.0,
        },
        {
            **_addon_contact_params(),
            "thermal_conductance": [1.0],
        },
        {
            **_addon_contact_params(),
            "parameters": {"surface_behavior": "hard"},
        },
        {
            **_addon_contact_params(),
            "kind": "contact",
        },
        {
            **_addon_contact_params(),
            "action": "__import__",
        },
    ],
)
def test_addon_rejects_connection_variant_confusion_before_dispatch(
    params: dict[str, object],
) -> None:
    service, operations = _service()
    before = len(operations.connection_calls)
    with pytest.raises(ServiceError):
        service(Request(700, "connection", params))
    assert len(operations.connection_calls) == before


@pytest.mark.parametrize("field", ("tolerance_m", "adjust"))
def test_addon_tie_requires_variant_controls_before_dispatch(field: str) -> None:
    service, operations = _service()
    params = _addon_tie_params()
    params.pop(field)
    before = len(operations.connection_calls)
    with pytest.raises(ServiceError):
        service(Request(725, "connection", params))
    assert len(operations.connection_calls) == before


@pytest.mark.parametrize("field", ("tolerance_m", "adjust"))
def test_addon_contact_forbids_present_tie_controls_before_dispatch(field: str) -> None:
    service, operations = _service()
    params = _addon_contact_params()
    params[field] = None
    before = len(operations.connection_calls)
    with pytest.raises(ServiceError):
        service(Request(726, "connection", params))
    assert len(operations.connection_calls) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("tolerance_m", -0.1),
        ("tolerance_m", 1e6 + 0.1),
        ("tolerance_m", True),
        ("tolerance_m", "1 m"),
        ("tolerance_m", math.nan),
        ("tolerance_m", math.inf),
        ("adjust", 0),
        ("adjust", 1),
        ("adjust", "false"),
        ("adjust", math.nan),
    ],
)
def test_addon_rejects_bad_tie_tolerance_and_adjust_before_dispatch(
    field: str, value: object,
) -> None:
    service, operations = _service()
    params = _addon_tie_params()
    params[field] = value
    before = len(operations.connection_calls)
    with pytest.raises(ServiceError):
        service(Request(750, "connection", params))
    assert len(operations.connection_calls) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("slave", {"object_name": "Upper", "subelements": []}),
        ("slave", {"object_name": "Upper", "subelements": ["Face1", "Face2"]}),
        ("slave", {"object_name": "Upper", "subelements": ["Edge1"]}),
        ("slave", {"object_name": "Upper", "subelements": ["Face0"]}),
        ("slave", {"object_name": "Upper", "subelements": ["Face1"], "kind": "Face"}),
        ("master", {"object_name": "Lower", "subelements": []}),
        ("master", {"object_name": "Lower", "subelements": ["Vertex1"]}),
        ("master", {"object_name": "Lower", "subelements": ["Face0"]}),
        ("master", {"object_name": "Lower", "subelements": ["Face1", "Face2"]}),
    ],
)
def test_addon_rejects_non_face_or_stale_connection_references_before_dispatch(
    field: str, value: object,
) -> None:
    service, operations = _service()
    params = _addon_tie_params()
    params[field] = value
    before = len(operations.connection_calls)
    with pytest.raises(ServiceError):
        service(Request(800, "connection", params))
    assert len(operations.connection_calls) == before


def test_addon_rejects_same_connection_face_before_dispatch() -> None:
    service, operations = _service()
    params = _addon_tie_params()
    params["master"] = {"object_name": "Upper", "subelements": ["Face3"]}
    before = len(operations.connection_calls)
    with pytest.raises(ServiceError):
        service(Request(801, "connection", params))
    assert len(operations.connection_calls) == before


def _addon_supported_amplitude_cases() -> tuple[tuple[str, dict[str, object], str], ...]:
    return (
        (
            "load",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "load_type": "force",
                "force_n": 10.0,
                "targets": [],
            },
            "calls",
        ),
        (
            "load",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "load_type": "pressure",
                "pressure_pa": 10.0,
                "targets": [],
            },
            "calls",
        ),
        (
            "boundary_condition",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "boundary_type": "displacement",
                "displacement_m": [0.0, 0.0, 0.001],
                "targets": [],
            },
            "calls",
        ),
        (
            "remote_load",
            _remote_request_params(),
            "remote_calls",
        ),
        (
            "remote_displacement",
            _remote_displacement_request_params(),
            "remote_displacement_calls",
        ),
    )


def test_addon_accepts_amplitude_on_supported_routes_and_forwards_it() -> None:
    service, operations = _service()
    for request_id, (method, params, call_attr) in enumerate(
        _addon_supported_amplitude_cases(), start=200
    ):
        params = dict(params)
        params["amplitude"] = _VALID_AMPLITUDE
        result = service(Request(request_id, method, params))
        assert result

        calls = getattr(operations, call_attr)
        if call_attr == "calls":
            forwarded = calls[-1][2]
        else:
            forwarded = calls[-1][0][1]
        assert forwarded["amplitude"] == _VALID_AMPLITUDE


@pytest.mark.parametrize(
    "label,value",
    [
        ("empty", []),
        ("one_point", [{"time_s": 0.0, "scale": 1.0}]),
        (
            "first_time_not_zero",
            [{"time_s": 0.1, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "duplicate_time",
            [{"time_s": 0.0, "scale": 1.0}, {"time_s": 0.0, "scale": 0.5}],
        ),
        (
            "decreasing_time",
            [
                {"time_s": 0.0, "scale": 1.0},
                {"time_s": 2.0, "scale": 0.5},
                {"time_s": 1.0, "scale": 0.5},
            ],
        ),
        (
            "negative_time",
            [{"time_s": -0.1, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_above_limit",
            [{"time_s": 0.0, "scale": 1.0}, {"time_s": 1e12 + 1.0, "scale": 1.0}],
        ),
        (
            "scale_above_limit",
            [{"time_s": 0.0, "scale": 1e9 + 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "scale_below_limit",
            [{"time_s": 0.0, "scale": -1e9 - 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_string",
            [{"time_s": "0.0", "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "scale_string",
            [{"time_s": 0.0, "scale": "1.0"}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_bool",
            [{"time_s": True, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "scale_bool",
            [{"time_s": 0.0, "scale": False}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_nan",
            [{"time_s": math.nan, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "scale_nan",
            [{"time_s": 0.0, "scale": math.nan}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "time_inf",
            [{"time_s": math.inf, "scale": 1.0}, {"time_s": 2.0, "scale": 1.0}],
        ),
        (
            "scale_inf",
            [{"time_s": 0.0, "scale": math.inf}, {"time_s": 1.0, "scale": 1.0}],
        ),
        (
            "nested_extra",
            [
                {"time_s": 0.0, "scale": 1.0, "metadata": {"source": "x"}},
                {"time_s": 1.0, "scale": 1.0},
            ],
        ),
        (
            "arbitrary_name",
            [
                {"time_s": 0.0, "scale": 1.0, "name": "Ramp"},
                {"time_s": 1.0, "scale": 1.0},
            ],
        ),
        (
            "arbitrary_kind",
            [
                {"time_s": 0.0, "scale": 1.0, "kind": "step"},
                {"time_s": 1.0, "scale": 1.0},
            ],
        ),
        ("wrong_nested_shape", [[0.0, 1.0], [1.0, 1.0]]),
        (
            "too_many_points",
            [{"time_s": float(index), "scale": 1.0} for index in range(257)],
        ),
    ],
)
def test_addon_rejects_bad_amplitude_before_dispatch(label: str, value: list[object]) -> None:
    del label
    service, operations = _service()
    for request_id, (method, params, call_attr) in enumerate(
        _addon_supported_amplitude_cases(), start=300
    ):
        params = dict(params)
        params["amplitude"] = value
        calls = getattr(operations, call_attr)
        before = len(calls)
        with pytest.raises(ServiceError):
            service(Request(request_id, method, params))
        assert len(calls) == before


def test_addon_rejects_amplitude_for_unsupported_routes_before_dispatch() -> None:
    unsupported = (
        (
            "load",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "load_type": "gravity",
                "acceleration_m_s2": [0.0, -9.81, 0.0],
                "targets": [],
                "amplitude": _VALID_AMPLITUDE,
            },
            "calls",
        ),
        (
            "load",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "load_type": "acceleration",
                "acceleration_m_s2": [0.0, -9.81, 0.0],
                "targets": [],
                "amplitude": _VALID_AMPLITUDE,
            },
            "calls",
        ),
        (
            "load",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "load_type": "centrifugal",
                "rotation_frequency_hz": 10.0,
                "axis": {"object_name": "Axis", "subelements": ["Edge1"]},
                "targets": [],
                "amplitude": _VALID_AMPLITUDE,
            },
            "centrifugal_calls",
        ),
        (
            "boundary_condition",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "boundary_type": "fixed",
                "targets": [],
                "amplitude": _VALID_AMPLITUDE,
            },
            "calls",
        ),
    )
    service, operations = _service()
    for request_id, (method, params, call_attr) in enumerate(unsupported, start=400):
        calls = getattr(operations, call_attr)
        before = len(calls)
        with pytest.raises(ServiceError):
            service(Request(request_id, method, params))
        assert len(calls) == before


def test_addon_revalidates_typed_load_requests() -> None:
    service, operations = _service()
    result = service(
        Request(
            1,
            "load",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "load_type": "force",
                "force_n": 10.0,
                "targets": [],
            },
        )
    )
    assert result["load_id"] == "Constraint"
    assert operations.calls[-1][1] == "force"

    bad_requests = (
        {"action": "__import__"},
        {"code": "print(1)"},
        {"pressure_pa": 2.0},
        {"force_n": float("nan")},
        {"force_n": True},
        {"force_n": "10"},
        {"targets": [{"object_name": "Face", "subelements": [], "extra": "x"}]},
    )
    for extra in bad_requests:
        params = {
            "action": "add",
            "analysis_id": "Analysis",
            "load_type": "force",
            "force_n": 10.0,
            "targets": [],
        }
        params.update(extra)
        with pytest.raises(ServiceError):
            service(Request(2, "load", params))


def test_addon_revalidates_typed_boundary_requests() -> None:
    service, operations = _service()
    result = service(
        Request(
            1,
            "boundary_condition",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "boundary_type": "fixed",
                "targets": [],
            },
        )
    )
    assert result["boundary_condition_id"] == "Constraint"
    assert operations.calls[-1][1] == "fixed"

    bad_requests = (
        {"action": "__import__"},
        {"code": "exec(1)"},
        {"displacement_m": [0.0, 0.0, 0.0]},
        {"boundary_type": "displacement"},
        {"boundary_type": "displacement", "displacement_m": [0.0, 0.0, math.inf]},
    )
    for extra in bad_requests:
        params = {
            "action": "add",
            "analysis_id": "Analysis",
            "boundary_type": "fixed",
            "targets": [],
        }
        params.update(extra)
        with pytest.raises(ServiceError):
            service(Request(2, "boundary_condition", params))


@pytest.mark.parametrize(
    "boundary_type,extra,expected",
    [
        ("pin", {}, {}),
        ("roller", {"axis": "y"}, {"axis": "y"}),
    ],
)
def test_addon_accepts_native_boundary_presets(boundary_type, extra, expected) -> None:
    service, operations = _service()
    params = {
        "action": "add",
        "analysis_id": "Analysis",
        "boundary_type": boundary_type,
        "targets": [],
    }
    params.update(extra)
    result = service(Request(3, "boundary_condition", params))
    assert result["boundary_condition_id"] == "Constraint"
    assert operations.calls[-1][1] == boundary_type
    for key, value in expected.items():
        assert operations.calls[-1][2][key] is value
    assert not {
        "xFree", "yFree", "zFree", "x", "y", "z",
        "rotxFree", "rotyFree", "rotzFree", "rotx", "roty", "rotz",
    }.intersection(operations.calls[-1][2])


def test_integer_json_normal_is_preserved_through_model_service_and_native_route() -> None:
    request = AddBoundaryConditionRequest(
        analysis_id="Analysis",
        boundary_type="roller",
        normal_m=[1, 0, 0],
    )
    service, operations = _service()
    params = request.model_dump(exclude_none=True)
    params["action"] = "add"
    service(Request(7, "boundary_condition", params))
    assert operations.calls[-1][1] == "roller"
    assert operations.calls[-1][2]["axis"] == "x"
    assert "normal_m" not in operations.calls[-1][2]


def test_addon_rejects_non_native_boundary_variants_before_dispatch() -> None:
    service, operations = _service()
    before = len(operations.calls)
    for extra in (
        {"boundary_type": "roller"},
        {"boundary_type": "roller", "axis": "q"},
        {"boundary_type": "roller", "normal_m": [1.0, 1.0, 0.0]},
    ):
        params = {
            "action": "add",
            "analysis_id": "Analysis",
            "targets": [],
        }
        params.update(extra)
        with pytest.raises(ServiceError):
            service(Request(4, "boundary_condition", params))
    assert len(operations.calls) == before


def test_explicit_empty_subelements_preserve_whole_shape_reference() -> None:
    service, operations = _service()
    service(
        Request(
            5,
            "boundary_condition",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "boundary_type": "pin",
                "targets": [{"object_name": "Geometry", "subelements": []}],
            },
        )
    )
    assert operations.calls[-1][2]["references"] == [
        {"object": "Geometry", "sub_element": ""}
    ]


def test_gui_object_only_selection_preserves_whole_shape_reference() -> None:
    class _ObjectOnlySelection:
        gui = None

        @staticmethod
        def capture() -> dict[str, list[object]]:
            return {"items": [{"object": "Geometry", "sub_elements": []}]}

    operations = _RecordingOperations()
    service = FEMService(
        operations=operations,
        selection=_ObjectOnlySelection(),
        jobs=object(),
        pipeline=object(),
    )
    service(
        Request(
            6,
            "boundary_condition",
            {
                "action": "add",
                "analysis_id": "Analysis",
                "boundary_type": "pin",
            },
        )
    )
    assert operations.calls[-1][2]["references"] == [
        {"object": "Geometry", "sub_element": ""}
    ]


def _remote_request_params() -> dict[str, object]:
    return {
        "action": "add",
        "analysis_id": "Analysis",
        "targets": [{"object_name": "Geometry", "subelements": ["Face1"]}],
        "reference_point_m": [0.0, 0.0, 0.0],
        "force_n": [1.0, 0.0, 0.0],
    }


def test_addon_accepts_a_valid_remote_load_without_a_generic_property_path() -> None:
    service, operations = _service()
    result = service(Request(10, "remote_load", _remote_request_params()))
    assert result["remote_load_id"] == "RemoteLoad"
    assert operations.remote_calls or operations.calls


@pytest.mark.parametrize("subelement", ("Vertex1", "Edge1", "Face1"))
def test_addon_remote_load_accepts_each_supported_single_shape_kind(subelement: str) -> None:
    service, _operations = _service()
    params = _remote_request_params()
    params["targets"] = [{"object_name": "Geometry", "subelements": [subelement]}]
    result = service(Request(16, "remote_load", params))
    assert result["remote_load_id"] == "RemoteLoad"


def test_addon_remote_load_rejects_zero_or_missing_payload() -> None:
    service, _operations = _service()
    for payload in (
        {},
        {"force_n": [0.0, 0.0, 0.0]},
        {"moment_n_m": [0.0, 0.0, 0.0]},
        {"force_n": [0.0, 0.0, 0.0], "moment_n_m": [0.0, 0.0, 0.0]},
    ):
        params = _remote_request_params()
        params.pop("force_n", None)
        params.update(payload)
        with pytest.raises(ServiceError):
            service(Request(11, "remote_load", params))


@pytest.mark.parametrize(
    "field,value",
    [
        ("reference_point_m", [1_000_000_000.1, 0.0, 0.0]),
        ("reference_point_m", [float("nan"), 0.0, 0.0]),
        ("reference_point_m", [float("inf"), 0.0, 0.0]),
        ("reference_point_m", [True, 0.0, 0.0]),
        ("reference_point_m", ["1 m", 0.0, 0.0]),
        ("reference_point_m", [0.0, 0.0]),
        ("reference_point_m", [0.0, 0.0, 0.0, 0.0]),
        ("force_n", [1_000_000_000_000_000.1, 0.0, 0.0]),
        ("force_n", [float("nan"), 0.0, 0.0]),
        ("force_n", [True, 0.0, 0.0]),
        ("force_n", ["1 N", 0.0, 0.0]),
        ("force_n", [0.0, 0.0]),
        ("moment_n_m", [1_000_000_000_000_000.1, 0.0, 0.0]),
        ("moment_n_m", [float("inf"), 0.0, 0.0]),
        ("moment_n_m", [0.0, False, 0.0]),
        ("moment_n_m", ["1 N*m", 0.0, 0.0]),
        ("moment_n_m", [0.0, 0.0, 0.0, 0.0]),
    ],
)
def test_addon_remote_load_rejects_nonfinite_coercion_and_bounds(
    field: str, value: list[object]
) -> None:
    service, _operations = _service()
    params = _remote_request_params()
    params[field] = value
    with pytest.raises(ServiceError):
        service(Request(12, "remote_load", params))


@pytest.mark.parametrize(
    "escape_field",
    (
        "code",
        "inp",
        "property",
        "native_property",
        "coordinate",
        "coordinate_system",
        "mode",
        "force_mode",
        "moment_mode",
    ),
)
def test_addon_remote_load_rejects_generic_escape_fields(escape_field: str) -> None:
    service, _operations = _service()
    params = _remote_request_params()
    params[escape_field] = "__import__('os').system('whoami')"
    with pytest.raises(ServiceError, match="unknown"):
        service(Request(13, "remote_load", params))


def test_addon_remote_load_rejects_empty_whole_mixed_or_unsupported_targets() -> None:
    service, _operations = _service()
    bad_targets = (
        [],
        [{"object_name": "Geometry", "subelements": []}],
        [{"object_name": "Geometry", "subelements": ["Face1", "Edge1"]}],
        [{"object_name": "Geometry", "subelements": ["Solid1"]}],
        [{"object_name": "Geometry", "subelements": ["Face1"], "code": "x"}],
        [{"object_name": "Geometry", "subelements": ["face1"]}],
        [{"object_name": "Geometry", "subelements": "Face1"}],
        [{"object_name": "Geometry", "subelements": [None]}],
        {"object_name": "Geometry", "subelements": ["Face1"]},
        [{"object_name": "Geometry", "subelements": ["Vertex"]}],
    )
    for targets in bad_targets:
        params = _remote_request_params()
        params["targets"] = targets
        with pytest.raises(ServiceError):
            service(Request(14, "remote_load", params))

    params = _remote_request_params()
    params["targets"] = [
        {"object_name": "Geometry", "subelements": ["Face{}".format(index)]}
        for index in range(129)
    ]
    with pytest.raises(ServiceError):
        service(Request(15, "remote_load", params))


def _remote_displacement_request_params() -> dict[str, object]:
    return {
        "action": "add",
        "analysis_id": "Analysis",
        "targets": [{"object_name": "Geometry", "subelements": ["Face1"]}],
        "reference_point_m": [0.0, 0.0, 0.0],
        "translation_m": [0.001, 0.0, 0.0],
        "rotation_rad": None,
    }


def test_addon_accepts_remote_displacement_and_preserves_free_vs_zero() -> None:
    service, operations = _service()
    result = service(Request(20, "remote_displacement", _remote_displacement_request_params()))
    assert result["remote_displacement_id"] == "RemoteDisplacement"
    assert operations.remote_displacement_calls

    for translation, rotation in (
        (None, [0.0, 0.5, 0.0]),
        ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]),
    ):
        params = _remote_displacement_request_params()
        params["translation_m"] = translation
        params["rotation_rad"] = rotation
        result = service(Request(21, "remote_displacement", params))
        assert result["remote_displacement_id"] == "RemoteDisplacement"
    assert len(operations.remote_displacement_calls) == 3


def test_addon_remote_displacement_requires_at_least_one_constrained_vector() -> None:
    service, operations = _service()
    before = len(operations.remote_displacement_calls)
    params = _remote_displacement_request_params()
    params["translation_m"] = None
    params["rotation_rad"] = None
    with pytest.raises(ServiceError):
        service(Request(22, "remote_displacement", params))
    assert len(operations.remote_displacement_calls) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("reference_point_m", [1_000_000_000.1, 0.0, 0.0]),
        ("reference_point_m", [float("nan"), 0.0, 0.0]),
        ("reference_point_m", [float("inf"), 0.0, 0.0]),
        ("reference_point_m", [True, 0.0, 0.0]),
        ("reference_point_m", ["1 m", 0.0, 0.0]),
        ("reference_point_m", [0.0, 0.0]),
        ("translation_m", [1_000_000_000.1, 0.0, 0.0]),
        ("translation_m", [float("nan"), 0.0, 0.0]),
        ("translation_m", [True, 0.0, 0.0]),
        ("translation_m", ["1 m", 0.0, 0.0]),
        ("translation_m", [0.0, 0.0, 0.0, 0.0]),
        ("rotation_rad", [1_000_000.1, 0.0, 0.0]),
        ("rotation_rad", [float("inf"), 0.0, 0.0]),
        ("rotation_rad", [False, 0.0, 0.0]),
        ("rotation_rad", ["1 deg", 0.0, 0.0]),
        ("rotation_rad", [0.0, 0.0, 0.0, 0.0]),
    ],
)
def test_addon_remote_displacement_rejects_bad_vectors(field: str, value: list[object]) -> None:
    service, operations = _service()
    before = len(operations.remote_displacement_calls)
    params = _remote_displacement_request_params()
    params[field] = value
    with pytest.raises(ServiceError):
        service(Request(23, "remote_displacement", params))
    assert len(operations.remote_displacement_calls) == before


@pytest.mark.parametrize(
    "escape_field",
    (
        "code",
        "inp",
        "property",
        "native_property",
        "formula",
        "path",
        "coordinate",
        "mode",
        "force_n",
        "pressure_pa",
    ),
)
def test_addon_remote_displacement_rejects_generic_or_load_fields(escape_field: str) -> None:
    service, operations = _service()
    before = len(operations.remote_displacement_calls)
    params = _remote_displacement_request_params()
    params[escape_field] = "__import__('os').system('whoami')"
    with pytest.raises(ServiceError, match="unknown"):
        service(Request(24, "remote_displacement", params))
    assert len(operations.remote_displacement_calls) == before


def test_addon_remote_displacement_rejects_empty_whole_mixed_or_unsupported_targets() -> None:
    service, operations = _service()
    before = len(operations.remote_displacement_calls)
    bad_targets = (
        [],
        [{"object_name": "Geometry", "subelements": []}],
        [{"object_name": "Geometry", "subelements": ["Face1", "Edge1"]}],
        [{"object_name": "Geometry", "subelements": ["Solid1"]}],
        [{"object_name": "Geometry", "subelements": ["Face1"], "code": "x"}],
        [{"object_name": "Geometry", "subelements": ["Face"]}],
        [{"object_name": "Geometry", "subelements": "Face1"}],
    )
    for targets in bad_targets:
        params = _remote_displacement_request_params()
        params["targets"] = targets
        with pytest.raises(ServiceError):
            service(Request(25, "remote_displacement", params))
    params = _remote_displacement_request_params()
    params["targets"] = [
        {"object_name": "Geometry", "subelements": ["Face{}".format(index)]}
        for index in range(129)
    ]
    with pytest.raises(ServiceError):
        service(Request(26, "remote_displacement", params))
    assert len(operations.remote_displacement_calls) == before


def test_acceleration_load_public_model_is_distinct_from_gravity_aliases() -> None:
    acceleration = AddLoadRequest(
        analysis_id="Analysis",
        load_type="acceleration",
        acceleration_m_s2=[0.0, -9.81, 0.0],
    )
    assert acceleration.acceleration_m_s2 == [0.0, -9.81, 0.0]

    with pytest.raises(ValidationError):
        AddLoadRequest(analysis_id="Analysis", load_type="acceleration")
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="acceleration",
            acceleration_m_s2=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="acceleration",
            acceleration_m_s2=[0.0, -9.81],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="acceleration",
            acceleration_m_s2=[float("nan"), 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="acceleration",
            acceleration_m_s2=[True, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="acceleration",
            acceleration_m_s2=["9.81 m/s^2", 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="acceleration",
            acceleration_m_s2=[0.0, 9.81, 0.0],
            force_n=1.0,
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="acceleration",
            acceleration_m_s2=[0.0, 9.81, 0.0],
            pressure_pa=1.0,
        )


def test_centrifugal_load_public_model_has_exclusive_bounded_axis_and_frequency() -> None:
    axis = {"object_name": "Axis", "subelements": ["Edge1"]}
    valid = AddLoadRequest(
        analysis_id="Analysis",
        load_type="centrifugal",
        rotation_frequency_hz=1e9,
        axis=axis,
        targets=[],
    )
    assert valid.rotation_frequency_hz == 1e9

    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz=0.0,
            axis=axis,
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz=-1.0,
            axis=axis,
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz=1_000_000_000.1,
            axis=axis,
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz=float("nan"),
            axis=axis,
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz=True,
            axis=axis,
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz="120 rpm",
            axis=axis,
        )
    for extra in (
        {"force_n": 1.0},
        {"pressure_pa": 1.0},
        {"acceleration_m_s2": [0.0, 9.81, 0.0]},
    ):
        with pytest.raises(ValidationError):
            AddLoadRequest(
                analysis_id="Analysis",
                load_type="centrifugal",
                rotation_frequency_hz=10.0,
                axis=axis,
                **extra,
            )


def _acceleration_request_params() -> dict[str, object]:
    return {
        "action": "add",
        "analysis_id": "Analysis",
        "load_type": "acceleration",
        "acceleration_m_s2": [0.0, -9.81, 0.0],
        "targets": [],
    }


def _centrifugal_request_params() -> dict[str, object]:
    return {
        "action": "add",
        "analysis_id": "Analysis",
        "load_type": "centrifugal",
        "rotation_frequency_hz": 10.0,
        "axis": {"object_name": "Axis", "subelements": ["Edge1"]},
        "targets": [],
    }


def test_addon_acceleration_route_maps_to_native_selfweight_and_rejects_conflicts() -> None:
    service, operations = _service()
    result = service(Request(30, "load", _acceleration_request_params()))
    assert result["load_id"] == "Constraint"
    assert operations.calls[-1][1] == "selfweight"

    for extra in (
        {"force_n": 1.0},
        {"pressure_pa": 1.0},
        {"acceleration_m_s2": [0.0, 0.0, 0.0]},
        {"acceleration_m_s2": [float("nan"), 0.0, 0.0]},
        {"acceleration_m_s2": [True, 0.0, 0.0]},
        {"acceleration_m_s2": ["9.81 m/s^2", 0.0, 0.0]},
        {"acceleration_m_s2": [0.0, 9.81]},
        {"code": "exec(1)"},
        {"inp": "*DLOAD"},
        {"property": "GravityAcceleration"},
        {"formula": "sin(t)"},
        {"path": "C:\\tmp\\load.inp"},
    ):
        before = len(operations.calls)
        params = _acceleration_request_params()
        params.update(extra)
        with pytest.raises(ServiceError):
            service(Request(31, "load", params))
        assert len(operations.calls) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("rotation_frequency_hz", 0.0),
        ("rotation_frequency_hz", -1.0),
        ("rotation_frequency_hz", 1_000_000_000.1),
        ("rotation_frequency_hz", float("nan")),
        ("rotation_frequency_hz", float("inf")),
        ("rotation_frequency_hz", True),
        ("rotation_frequency_hz", "120 rpm"),
    ],
)
def test_addon_centrifugal_rejects_bad_frequency(field: str, value: object) -> None:
    service, operations = _service()
    before = len(operations.centrifugal_calls)
    params = _centrifugal_request_params()
    params[field] = value
    with pytest.raises(ServiceError):
        service(Request(32, "load", params))
    assert len(operations.centrifugal_calls) == before


def test_addon_centrifugal_accepts_all_or_solid_targets_and_maps_axis() -> None:
    service, operations = _service()
    result = service(Request(33, "load", _centrifugal_request_params()))
    assert result["load_id"] == "Centrifugal"
    assert operations.centrifugal_calls

    params = _centrifugal_request_params()
    params["targets"] = [{"object_name": "Body", "subelements": ["Solid1"]}]
    result = service(Request(34, "load", params))
    assert result["load_id"] == "Centrifugal"
    assert len(operations.centrifugal_calls) == 2


def test_addon_centrifugal_rejects_axis_and_target_shape_confusion() -> None:
    service, operations = _service()
    before = len(operations.centrifugal_calls)
    bad_axis = (
        {"object_name": "Axis", "subelements": []},
        {"object_name": "Axis", "subelements": ["Edge1", "Edge2"]},
        {"object_name": "Axis", "subelements": ["Face1"]},
        {"object_name": "Axis", "subelements": ["Vertex1"]},
        {"object_name": "Axis", "subelements": ["EdgeSpline"]},
        {"object_name": "Axis", "subelements": ["Edge1"], "code": "x"},
    )
    for axis in bad_axis:
        params = _centrifugal_request_params()
        params["axis"] = axis
        with pytest.raises(ServiceError):
            service(Request(35, "load", params))

    bad_targets = (
        [{"object_name": "Body", "subelements": ["Face1"]}],
        [{"object_name": "Body", "subelements": ["Edge1"]}],
        [{"object_name": "Body", "subelements": ["Vertex1"]}],
        [{"object_name": "Body", "subelements": []}],
        [{"object_name": "Body", "subelements": ["Solid1", "Face1"]}],
        [{"object_name": "Body", "subelements": ["Solid1"], "property": "Shape"}],
    )
    for targets in bad_targets:
        params = _centrifugal_request_params()
        params["targets"] = targets
        with pytest.raises(ServiceError):
            service(Request(36, "load", params))
    assert len(operations.centrifugal_calls) == before


@pytest.mark.parametrize(
    "escape_field",
    (
        "code",
        "inp",
        "property",
        "native_property",
        "formula",
        "path",
        "rotation_frequency_rpm",
        "mode",
    ),
)
def test_addon_centrifugal_rejects_generic_or_unit_alias_fields(escape_field: str) -> None:
    service, operations = _service()
    before = len(operations.centrifugal_calls)
    params = _centrifugal_request_params()
    params[escape_field] = "__import__('os').system('whoami')"
    with pytest.raises(ServiceError, match="unknown"):
        service(Request(37, "load", params))
    assert len(operations.centrifugal_calls) == before


def test_addon_centrifugal_rejects_other_load_fields() -> None:
    service, operations = _service()
    for extra in (
        {"force_n": 1.0},
        {"pressure_pa": 1.0},
        {"acceleration_m_s2": [0.0, 9.81, 0.0]},
    ):
        before = len(operations.centrifugal_calls)
        params = _centrifugal_request_params()
        params.update(extra)
        with pytest.raises(ServiceError):
            service(Request(38, "load", params))
        assert len(operations.centrifugal_calls) == before


# One minimal request for every public method/action.  Unknown fields are
# checked before dispatch, so these cases do not need a live FreeCAD document.
_ROUTE_CASES: tuple[tuple[tuple[str, str], dict[str, object]], ...] = (
    (("status", "get"), {"action": "get"}),
    (("document", "active"), {"action": "active"}),
    (("selection", "get"), {"action": "get"}),
    (("view", "set"), {"action": "set"}),
    (("capture", "capture"), {"action": "capture", "scope": "viewport"}),
    (("open", "open"), {"action": "open", "path": "model.FCStd"}),
    (("save", "save"), {"action": "save"}),
    (("analysis", "create"), {"action": "create"}),
    (("material", "assign"), {"action": "assign", "analysis_id": "Analysis"}),
    (
        ("constraint", "add"),
        {"action": "add", "analysis_id": "Analysis", "constraint_type": "fixed"},
    ),
    (
        ("connection", "add"),
        {
            "action": "add",
            "analysis_id": "Analysis",
            "connection_type": "tie",
            "slave": {"object_name": "Upper", "subelements": ["Face3"]},
            "master": {"object_name": "Lower", "subelements": ["Face7"]},
            "tolerance_m": 0.0,
            "adjust": False,
        },
    ),
    (
        ("load", "add"),
        {
            "action": "add",
            "analysis_id": "Analysis",
            "load_type": "force",
            "force_n": 1.0,
        },
    ),
    (
        ("boundary_condition", "add"),
        {"action": "add", "analysis_id": "Analysis", "boundary_type": "fixed"},
    ),
    (
        ("remote_load", "add"),
        {
            "action": "add",
            "analysis_id": "Analysis",
            "targets": [{"object_name": "Geometry", "subelements": ["Face1"]}],
            "reference_point_m": [0.0, 0.0, 0.0],
            "force_n": [1.0, 0.0, 0.0],
        },
    ),
    (
        ("remote_displacement", "add"),
        {
            "action": "add",
            "analysis_id": "Analysis",
            "targets": [{"object_name": "Geometry", "subelements": ["Face1"]}],
            "reference_point_m": [0.0, 0.0, 0.0],
            "translation_m": [0.001, 0.0, 0.0],
            "rotation_rad": None,
        },
    ),
    (("mesh", "create"), {"action": "create", "analysis_id": "Analysis"}),
    (
        ("element_geometry", "assign"),
        {
            "action": "assign",
            "analysis_id": "Analysis",
            "kind": "shell",
            "targets": [{"object_name": "Geometry", "subelements": ["Face1"]}],
            "thickness_m": 0.001,
        },
    ),
    (("validate", "validate"), {"action": "validate", "analysis_id": "Analysis"}),
    (("jobs", "start"), {"action": "start", "analysis_id": "Analysis"}),
    (("jobs", "get"), {"action": "get", "job_id": "Job"}),
    (("jobs", "list"), {"action": "list"}),
    (("jobs", "cancel"), {"action": "cancel", "job_id": "Job"}),
    (("results", "get"), {"action": "get", "analysis_id": "Analysis"}),
    (("results", "show"), {"action": "show", "analysis_id": "Analysis"}),
)


def test_addon_status_advertises_all_analysis_types_and_route_parity() -> None:
    service, _operations = _service()
    status = service(Request(90, "status", {"action": "get"}))
    assert set(status["capabilities"]["analysis_types"]) == {
        "static",
        "frequency",
        "buckling",
    }
    assert len(_ROUTE_CASES) == 24
    assert {pair for pair, _base in _ROUTE_CASES} == set(PUBLIC_TOOL_ACTIONS.values())


def test_addon_status_exposes_exact_bounded_r6_future_gates() -> None:
    service, _operations = _service()
    expected = [
        "load_case",
        "multi_step",
        "combination",
        "envelope",
        "bolt_pretension",
        "mechanical_initial_stress_strain",
        "concentrated_mass_rotational_inertia",
        "damper",
        "connector_release",
    ]
    status = service(Request(91, "status", {"action": "get"}))
    assert status["capabilities"]["future_gates"] == expected
    assert len(status["capabilities"]["future_gates"]) == 9
    for model in PUBLIC_REQUEST_MODELS.values():
        assert not set(expected).intersection(model.model_fields)
        assert not set(expected).intersection(model.model_json_schema().get("properties", {}))
    # The status response must not expose a mutable module-level list.
    status["capabilities"]["future_gates"].append("unexpected")
    refreshed = service(Request(92, "status", {"action": "get"}))
    assert refreshed["capabilities"]["future_gates"] == expected


def test_addon_status_exposes_bounded_native_element_geometry_capabilities() -> None:
    service, _operations = _service()
    capabilities = service(Request(93, "status", {"action": "get"}))["capabilities"]
    assert capabilities["element_dimensions"] == ["1d", "2d", "3d"]
    assert capabilities["element_geometry"]["shell"]["references"] == "Face"
    assert capabilities["element_geometry"]["beam_section"]["references"] == "Edge"
    assert capabilities["element_geometry"]["beam_rotation"]["references"] == "Edge"
    capabilities["element_geometry"]["beam_section"]["section_types"].append("escape")
    refreshed = service(Request(94, "status", {"action": "get"}))["capabilities"]
    assert "escape" not in refreshed["element_geometry"]["beam_section"]["section_types"]


@pytest.mark.parametrize("escape_field", ("code", "inp", "property", "property_name", "native_property"))
def test_addon_every_route_rejects_native_escape_fields(escape_field: str) -> None:
    """No route/action may pass code, INP, or native property data downstream."""

    service, _operations = _service()
    assert {pair for pair, _base in _ROUTE_CASES} == set(PUBLIC_TOOL_ACTIONS.values())
    for (method, action), base in _ROUTE_CASES:
        params = dict(base)
        params[escape_field] = "__import__('os').system('whoami')"
        with pytest.raises(ServiceError, match="unknown fields"):
            service(Request(100, method, params))


@pytest.mark.parametrize(
    "future_field",
    [
        "load_case",
        "multi_step",
        "combination",
        "envelope",
        "bolt_pretension",
        "mechanical_initial_stress_strain",
        "concentrated_mass_rotational_inertia",
        "damper",
        "connector_release",
    ],
)
def test_addon_r6_future_fields_are_unknown_on_every_route(future_field: str) -> None:
    """R6 gates are status-only; no route accepts a future feature field."""

    service, _operations = _service()
    for (method, _action), base in _ROUTE_CASES:
        params = dict(base)
        params[future_field] = {"enabled": True}
        with pytest.raises(ServiceError, match="unknown fields"):
            service(Request(110, method, params))


def test_addon_every_route_rejects_arbitrary_actions() -> None:
    service, _operations = _service()
    for (method, _action), base in _ROUTE_CASES:
        params = dict(base)
        params["action"] = "__import__"
        with pytest.raises(ServiceError, match="unsupported action"):
            service(Request(101, method, params))


def test_zero_gravity_is_rejected_at_both_boundaries() -> None:
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="A",
            load_type="gravity",
            acceleration_m_s2=[0.0, 0.0, 0.0],
        )

    service, _operations = _service()
    with pytest.raises(ServiceError, match="non-zero"):
        service(
            Request(
                102,
                "load",
                {
                    "action": "add",
                    "analysis_id": "Analysis",
                    "load_type": "gravity",
                    "acceleration_m_s2": [0.0, 0.0, 0.0],
                },
            )
        )


def test_legacy_constraint_targets_reject_nested_escape_fields() -> None:
    """Compatibility constraints must close nested EntityRef objects too."""

    service, _operations = _service()
    for escape_field in ("code", "inp", "property"):
        with pytest.raises(ServiceError, match="unknown"):
            service(
                Request(
                    103,
                    "constraint",
                    {
                        "action": "add",
                        "analysis_id": "Analysis",
                        "constraint_type": "fixed",
                        "targets": [
                            {
                                "object_name": "Face",
                                "subelements": [],
                                escape_field: "__import__('os').system('whoami')",
                            }
                        ],
                    },
                )
            )
