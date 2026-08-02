import math

import pytest
from pydantic import ValidationError

from freecad_fem_mcp.models import (
    AnalysisRequest,
    ConstraintRequest,
    EntityRef,
    MaterialRequest,
    MeshRequest,
    StatusRequest,
    ViewRequest,
)


def test_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        StatusRequest(typo=True)


def test_models_reject_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        ViewRequest(fit_margin=math.nan)
    with pytest.raises(ValidationError):
        MaterialRequest(youngs_modulus_pa=math.inf)


def test_static_solver_and_gmsh_are_the_only_mvp_choices() -> None:
    assert AnalysisRequest().analysis_type == "static"
    assert MeshRequest(analysis_id="Analysis").algorithm == "gmsh"
    with pytest.raises(ValidationError):
        AnalysisRequest(analysis_type="frequency")
    with pytest.raises(ValidationError):
        MeshRequest(analysis_id="Analysis", algorithm="netgen")


def test_constraint_targets_are_explicit_and_empty_is_selection() -> None:
    current_selection = ConstraintRequest(analysis_id="Analysis", constraint_type="fixed")
    assert current_selection.targets == []
    target = ConstraintRequest(
        analysis_id="Analysis",
        constraint_type="force",
        targets=[EntityRef(object_name="Bracket", subelements=["Face3"])],
        force_n=[10.0, 0.0, 0.0],
    )
    assert target.targets[0].object_name == "Bracket"


def test_path_controls_are_not_arbitrary_commands() -> None:
    with pytest.raises(ValidationError):
        # NUL and control characters are rejected before crossing the bridge.
        from freecad_fem_mcp.models import OpenRequest

        OpenRequest(path="bad\x00path")
