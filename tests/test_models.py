import math

import pytest
from pydantic import ValidationError

from freecad_fem_mcp.models import (
    AddBoundaryConditionRequest,
    AnalysisRequest,
    ConstraintRequest,
    AddLoadRequest,
    AddRemoteDisplacementRequest,
    AddRemoteLoadRequest,
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


def test_typed_loads_require_only_their_matching_si_value() -> None:
    force = AddLoadRequest(analysis_id="Analysis", load_type="force", force_n=10.0)
    assert force.force_n == 10.0
    pressure = AddLoadRequest(analysis_id="Analysis", load_type="pressure", pressure_pa=12.5)
    assert pressure.pressure_pa == 12.5
    gravity = AddLoadRequest(
        analysis_id="Analysis",
        load_type="gravity",
        acceleration_m_s2=[0.0, -9.81, 0.0],
    )
    assert gravity.acceleration_m_s2 == [0.0, -9.81, 0.0]
    acceleration = AddLoadRequest(
        analysis_id="Analysis",
        load_type="acceleration",
        acceleration_m_s2=[0.0, 1.25, 0.0],
    )
    assert acceleration.acceleration_m_s2 == [0.0, 1.25, 0.0]

    with pytest.raises(ValidationError):
        AddLoadRequest(analysis_id="Analysis", load_type="force")
    with pytest.raises(ValidationError):
        AddLoadRequest(analysis_id="Analysis", load_type="pressure", force_n=1.0)
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="gravity",
            acceleration_m_s2=[0.0, -9.81],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="gravity",
            acceleration_m_s2=[0.0, -9.81, 0.0],
            pressure_pa=1.0,
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="gravity",
            acceleration_m_s2=[0.0, 0.0, 0.0],
        )
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
            acceleration_m_s2=[0.0, 1.0, 0.0],
            force_n=1.0,
        )
    centrifugal = AddLoadRequest(
        analysis_id="Analysis",
        load_type="centrifugal",
        rotation_frequency_hz=60.0,
        axis={"object_name": "Rotor", "subelements": ["Edge1"]},
    )
    assert centrifugal.rotation_frequency_hz == 60.0
    assert centrifugal.axis is not None and centrifugal.axis.subelements == ["Edge1"]
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz=60.0,
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz=60.0,
            axis={"object_name": "Rotor", "subelements": ["Face1"]},
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz=0.0,
            axis={"object_name": "Rotor", "subelements": ["Edge1"]},
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="centrifugal",
            rotation_frequency_hz=60.0,
            axis={"object_name": "Rotor", "subelements": ["Edge1"]},
            acceleration_m_s2=[0.0, 1.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(analysis_id="Analysis", load_type="force", force_n=math.nan)


def test_boundary_condition_values_are_type_specific() -> None:
    fixed = AddBoundaryConditionRequest(analysis_id="Analysis", boundary_type="fixed")
    assert fixed.displacement_m is None
    displacement = AddBoundaryConditionRequest(
        analysis_id="Analysis",
        boundary_type="displacement",
        displacement_m=[0.0, 0.001, 0.0],
    )
    assert displacement.displacement_m == [0.0, 0.001, 0.0]

    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="Analysis",
            boundary_type="fixed",
            displacement_m=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(analysis_id="Analysis", boundary_type="displacement")
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="Analysis",
            boundary_type="displacement",
            displacement_m=[0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="Analysis",
            boundary_type="displacement",
            displacement_m=[0.0, math.inf, 0.0],
        )


def test_remote_load_requires_bounded_targets_and_nonzero_force_or_moment() -> None:
    targets = [EntityRef(object_name="Bracket", subelements=["Face1"])]
    force = AddRemoteLoadRequest(
        analysis_id="Analysis",
        targets=targets,
        reference_point_m=[0.0, 0.0, 0.0],
        force_n=[100.0, 0.0, 0.0],
    )
    assert force.reference_point_m == [0.0, 0.0, 0.0]
    assert force.force_n == [100.0, 0.0, 0.0]

    moment_only = AddRemoteLoadRequest(
        analysis_id="Analysis",
        targets=targets,
        reference_point_m=[1.0, -2.0, 3.0],
        force_n=[0.0, 0.0, 0.0],
        moment_n_m=[0.0, 1.0, 0.0],
    )
    assert moment_only.moment_n_m == [0.0, 1.0, 0.0]

    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            analysis_id="Analysis",
            targets=[],
            reference_point_m=[0.0, 0.0, 0.0],
            force_n=[1.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[0.0, 0.0, 0.0],
            force_n=[0.0, 0.0, 0.0],
            moment_n_m=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[1_000_000_000.1, 0.0, 0.0],
            force_n=[1.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[0.0, 0.0, 0.0],
            force_n=[1_000_000_000_000_000.1, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteLoadRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[0.0, 0.0, 0.0],
            force_n=[1.0, 0.0, 0.0],
            coordinate_system="global",
        )


def test_remote_displacement_requires_a_constrained_global_component() -> None:
    targets = [EntityRef(object_name="Bracket", subelements=["Face1"])]
    translation = AddRemoteDisplacementRequest(
        analysis_id="Analysis",
        targets=targets,
        reference_point_m=[0.0, 0.0, 0.0],
        translation_m=[0.0, None, None],
    )
    assert translation.translation_m == [0.0, None, None]
    rotation = AddRemoteDisplacementRequest(
        analysis_id="Analysis",
        targets=targets,
        reference_point_m=[1.0, 2.0, 3.0],
        translation_m=[None, None, None],
        rotation_rad=[None, 0.25, None],
    )
    assert rotation.rotation_rad == [None, 0.25, None]

    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[0.0, 0.0, 0.0],
            translation_m=[None, None, None],
            rotation_rad=[None, None, None],
        )
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[0.0, 0.0, 0.0],
            translation_m=[1e9 + 1.0, None, None],
        )
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[0.0, 0.0, 0.0],
            rotation_rad=[1e6 + 1.0, None, None],
        )
    with pytest.raises(ValidationError):
        AddRemoteDisplacementRequest(
            analysis_id="Analysis",
            targets=targets,
            reference_point_m=[0.0, 0.0, 0.0],
            translation_m=[0.001, None, None],
            force_n=[1.0, 0.0, 0.0],
        )


def test_path_controls_are_not_arbitrary_commands() -> None:
    with pytest.raises(ValidationError):
        # NUL and control characters are rejected before crossing the bridge.
        from freecad_fem_mcp.models import OpenRequest

        OpenRequest(path="bad\x00path")
