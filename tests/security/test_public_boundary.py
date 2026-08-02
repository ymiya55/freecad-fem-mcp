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


class _RecordingOperations:
    app = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def add_constraint(self, analysis_id: str, kind: str, data: dict[str, object]) -> dict[str, str]:
        self.calls.append((analysis_id, kind, data))
        return {"name": "Constraint"}


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
