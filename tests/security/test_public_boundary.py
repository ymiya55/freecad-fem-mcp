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
    AddLoadRequest,
    AddRemoteLoadRequest,
    CreateMeshRequest,
    GetResultsRequest,
    PUBLIC_REQUEST_MODELS,
)
from freecad_fem_mcp.server import PUBLIC_TOOL_ACTIONS, TOOL_NAMES  # noqa: E402

from FreeCADFEMMCP.protocol import ALLOWED_METHODS, Request  # noqa: E402
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


class _RecordingOperations:
    app = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.remote_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def add_constraint(self, analysis_id: str, kind: str, data: dict[str, object]) -> dict[str, str]:
        self.calls.append((analysis_id, kind, data))
        return {"name": "Constraint"}

    def add_remote_load(self, *args: object, **kwargs: object) -> dict[str, str]:
        self.remote_calls.append((args, kwargs))
        return {"name": "RemoteLoad"}


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
    (("mesh", "create"), {"action": "create", "analysis_id": "Analysis"}),
    (("validate", "validate"), {"action": "validate", "analysis_id": "Analysis"}),
    (("jobs", "start"), {"action": "start", "analysis_id": "Analysis"}),
    (("jobs", "get"), {"action": "get", "job_id": "Job"}),
    (("jobs", "list"), {"action": "list"}),
    (("jobs", "cancel"), {"action": "cancel", "job_id": "Job"}),
    (("results", "get"), {"action": "get", "analysis_id": "Analysis"}),
    (("results", "show"), {"action": "show", "analysis_id": "Analysis"}),
)


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
