import math

import pytest
from pydantic import ValidationError

from freecad_fem_mcp.models import (
    AddBoundaryConditionRequest,
    AddConnectionRequest,
    AnalysisRequest,
    AmplitudePoint,
    ConstraintRequest,
    AddLoadRequest,
    AddRemoteDisplacementRequest,
    AddRemoteLoadRequest,
    EntityRef,
    CreateAnalysisRequest,
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


def test_analysis_variants_require_matching_solver_controls() -> None:
    assert AnalysisRequest().analysis_type == "static"
    assert MeshRequest(analysis_id="Analysis").algorithm == "gmsh"

    frequency = CreateAnalysisRequest(
        analysis_type="frequency",
        eigenmodes_count=6,
        frequency_low_hz=10.0,
        frequency_high_hz=100.0,
    )
    assert frequency.eigenmodes_count == 6
    assert AnalysisRequest(analysis_type="frequency", eigenmodes_count=2).frequency_low_hz is None

    buckling = CreateAnalysisRequest(
        analysis_type="buckling", buckling_factors=3, buckling_accuracy=0.01
    )
    assert buckling.buckling_factors == 3

    with pytest.raises(ValidationError):
        CreateAnalysisRequest(analysis_type="frequency")
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(analysis_type="frequency", eigenmodes_count=2, frequency_low_hz=1.0)
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(
            analysis_type="frequency", eigenmodes_count=2,
            frequency_low_hz=10.0, frequency_high_hz=10.0,
        )
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(analysis_type="frequency", eigenmodes_count=2, buckling_factors=1)
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(analysis_type="buckling", buckling_factors=1)
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(analysis_type="buckling", buckling_factors=1, buckling_accuracy=0.1, eigenmodes_count=2)
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(analysis_type="static", eigenmodes_count=1)
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(analysis_type="frequency", eigenmodes_count=True)
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(analysis_type="buckling", buckling_factors=1, buckling_accuracy=0.0)
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(analysis_type="frequency", eigenmodes_count=101)
    with pytest.raises(ValidationError):
        MeshRequest(analysis_id="Analysis", algorithm="netgen")


def test_connection_contract_is_closed_and_face_only() -> None:
    base = {
        "analysis_id": "Analysis",
        "slave": {"object_name": "Slave", "subelements": ["Face1"]},
        "master": {"object_name": "Master", "subelements": ["Face2"]},
    }
    tie = AddConnectionRequest(
        **base, connection_type="tie", tolerance_m=0.001, adjust=True
    )
    assert tie.connection_type == "tie"
    contact = AddConnectionRequest(**base, connection_type="contact", surface_behavior="hard")
    assert contact.surface_behavior == "hard"

    invalid = (
        {**base, "connection_type": "tie", "adjust": True},
        {**base, "connection_type": "tie", "tolerance_m": 0.1, "adjust": True, "surface_behavior": "hard"},
        {**base, "connection_type": "contact"},
        {**base, "connection_type": "contact", "surface_behavior": "hard", "tolerance_m": 0.1},
        {**base, "connection_type": "contact", "surface_behavior": "hard", "adjust": False},
        {**base, "connection_type": "tie", "tolerance_m": 0.1, "adjust": True,
         "slave": {"object_name": "Slave", "subelements": ["Edge1"]}},
        {**base, "connection_type": "tie", "tolerance_m": 0.1, "adjust": True,
         "slave": {"object_name": "Slave", "subelements": ["Face1", "Face2"]}},
        {**base, "connection_type": "tie", "tolerance_m": 0.1, "adjust": True,
         "master": {"object_name": "Slave", "subelements": ["Face1"]}},
        {**base, "connection_type": "tie", "tolerance_m": 0.1, "adjust": True, "friction": 0.2},
    )
    for params in invalid:
        with pytest.raises(ValidationError):
            AddConnectionRequest(**params)


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


@pytest.mark.parametrize("boundary_type", ["pin"])
def test_native_boundary_presets_have_closed_payloads(boundary_type: str) -> None:
    request = AddBoundaryConditionRequest(analysis_id="Analysis", boundary_type=boundary_type)
    assert request.displacement_m is None
    assert request.axis is None
    assert request.normal_m is None
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="Analysis", boundary_type=boundary_type, displacement_m=[0.0, 0.0, 0.0]
        )


def test_roller_requires_axis_or_axis_aligned_normal() -> None:
    assert AddBoundaryConditionRequest(
        analysis_id="Analysis", boundary_type="roller", axis="z"
    ).axis == "z"
    assert AddBoundaryConditionRequest(
        analysis_id="Analysis", boundary_type="roller", normal_m=[0.0, -1.0, 0.0]
    ).normal_m == [0.0, -1.0, 0.0]
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(analysis_id="Analysis", boundary_type="roller")
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="Analysis", boundary_type="roller", axis="x", normal_m=[1.0, 0.0, 0.0]
        )
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="Analysis", boundary_type="roller", normal_m=[1.0, 1.0, 0.0]
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


def test_bounded_amplitude_requires_ordered_finite_samples() -> None:
    amplitude = [AmplitudePoint(time_s=0.0, scale=0.0), AmplitudePoint(time_s=1.0, scale=1.0)]
    load = AddLoadRequest(
        analysis_id="Analysis",
        load_type="force",
        force_n=10.0,
        amplitude=amplitude,
    )
    assert load.amplitude == amplitude

    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="force",
            force_n=10.0,
            amplitude=[
                {"time_s": 0.1, "scale": 0.0},
                {"time_s": 1.0, "scale": 1.0},
            ],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="force",
            force_n=10.0,
            amplitude=[
                {"time_s": 0.0, "scale": 0.0},
                {"time_s": 0.0, "scale": 1.0},
            ],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="force",
            force_n=10.0,
            amplitude=[{"time_s": 0.0, "scale": 0.0}],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="force",
            force_n=10.0,
            amplitude=[
                {"time_s": 0.0, "scale": 0.0},
                {"time_s": 1e12 + 1.0, "scale": 1.0},
            ],
        )
    with pytest.raises(ValidationError):
        AddLoadRequest(
            analysis_id="Analysis",
            load_type="force",
            force_n=10.0,
            amplitude=[
                {"time_s": 0.0, "scale": 0.0},
                {"time_s": 1.0, "scale": 1e9 + 1.0},
            ],
        )
    with pytest.raises(ValidationError):
        AmplitudePoint(time_s=0.0, scale=0.0, name="not-allowed")


def test_amplitude_is_gated_to_supported_loads_and_boundaries() -> None:
    amplitude = [
        {"time_s": 0.0, "scale": 0.0},
        {"time_s": 1.0, "scale": 1.0},
    ]
    # Existing non-amplitude load types remain available for their established
    # contracts, but cannot opt into this bounded amplitude feature.
    unsupported = {
        "gravity": {"acceleration_m_s2": [0.0, -9.81, 0.0]},
        "acceleration": {"acceleration_m_s2": [0.0, 1.25, 0.0]},
        "centrifugal": {
            "rotation_frequency_hz": 60.0,
            "axis": {"object_name": "Rotor", "subelements": ["Edge1"]},
        },
    }
    for load_type, values in unsupported.items():
        with pytest.raises(ValidationError):
            AddLoadRequest(
                analysis_id="Analysis",
                load_type=load_type,
                amplitude=amplitude,
                **values,
            )

    displacement = AddBoundaryConditionRequest(
        analysis_id="Analysis",
        boundary_type="displacement",
        displacement_m=[0.0, 0.001, 0.0],
        amplitude=amplitude,
    )
    assert displacement.amplitude is not None
    with pytest.raises(ValidationError):
        AddBoundaryConditionRequest(
            analysis_id="Analysis",
            boundary_type="fixed",
            amplitude=amplitude,
        )

    targets = [EntityRef(object_name="Bracket", subelements=["Face1"])]
    remote_load = AddRemoteLoadRequest(
        analysis_id="Analysis",
        targets=targets,
        reference_point_m=[0.0, 0.0, 0.0],
        force_n=[100.0, 0.0, 0.0],
        amplitude=amplitude,
    )
    assert remote_load.amplitude is not None
    remote_displacement = AddRemoteDisplacementRequest(
        analysis_id="Analysis",
        targets=targets,
        reference_point_m=[0.0, 0.0, 0.0],
        translation_m=[0.0, None, None],
        amplitude=amplitude,
    )
    assert remote_displacement.amplitude is not None
