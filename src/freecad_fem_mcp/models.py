"""Strict request and response models for the public MCP tool surface.

The server accepts data from an untrusted model/client.  Keeping the wire models
in one module makes the boundary auditable: unknown fields are rejected, text and
collections are bounded, and floating point values must be finite.  The Addon may
return richer payloads, but requests never contain an escape hatch for arbitrary
code, paths, resources, or processes.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

# Keep these limits deliberately conservative.  They protect both the stdio
# process and the FreeCAD GUI from accidentally huge model-generated requests.
MAX_TEXT = 256
MAX_PATH = 512
MAX_LIST = 128
MAX_VALUES = 32


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("value must be finite")
    return value


def _non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


def _finite_json(value: Any) -> Any:
    """Reject NaN/Infinity recursively in an arbitrary JSON payload."""

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("payload numbers must be finite")
    if isinstance(value, dict):
        if len(value) > MAX_LIST:
            raise ValueError("payload objects are too large")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > MAX_TEXT:
                raise ValueError("payload keys must be bounded strings")
            _finite_json(item)
    elif isinstance(value, list):
        if len(value) > MAX_LIST:
            raise ValueError("payload lists are too long")
        for item in value:
            _finite_json(item)
    return value


FiniteFloat = Annotated[StrictFloat, AfterValidator(_finite)]
PositiveFiniteFloat = Annotated[StrictFloat, Field(gt=0), AfterValidator(_finite)]
NonNegativeFiniteFloat = Annotated[StrictFloat, Field(ge=0), AfterValidator(_finite)]
BoundedText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=MAX_TEXT),
    AfterValidator(_non_empty),
]
OptionalText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=MAX_TEXT),
    AfterValidator(_non_empty),
]
BoundedPath = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=MAX_PATH),
    AfterValidator(_non_empty),
]
BoundedList = Annotated[list[Any], Field(max_length=MAX_LIST)]
StringList = Annotated[list[BoundedText], Field(max_length=MAX_LIST)]
ValueList = Annotated[list[FiniteFloat], Field(max_length=MAX_VALUES)]
Vector3 = Annotated[list[FiniteFloat], Field(min_length=3, max_length=3)]
RemoteReferenceComponent = Annotated[FiniteFloat, Field(ge=-1e9, le=1e9)]
RemoteLoadComponent = Annotated[FiniteFloat, Field(ge=-1e15, le=1e15)]
RemoteReferenceVector3 = Annotated[
    list[RemoteReferenceComponent], Field(min_length=3, max_length=3)
]
RemoteLoadVector3 = Annotated[list[RemoteLoadComponent], Field(min_length=3, max_length=3)]
RemoteDisplacementComponent = Annotated[FiniteFloat, Field(ge=-1e9, le=1e9)] | None
RemoteRotationComponent = Annotated[FiniteFloat, Field(ge=-1e6, le=1e6)] | None
RemoteDisplacementVector3 = Annotated[
    list[RemoteDisplacementComponent], Field(min_length=3, max_length=3)
]
RemoteRotationVector3 = Annotated[list[RemoteRotationComponent], Field(min_length=3, max_length=3)]
TransformRotationComponent = Annotated[
    StrictFloat, Field(ge=-1e6, le=1e6), AfterValidator(_finite)
]
TransformRotationVector3 = Annotated[
    list[TransformRotationComponent], Field(min_length=3, max_length=3)
]
CentrifugalFrequencyHz = Annotated[StrictFloat, Field(gt=0, le=1e9), AfterValidator(_finite)]
BoundedInt = Annotated[StrictInt, Field(ge=0, le=2_147_483_647)]
# Modal result selection is deliberately narrower than the solver's mode count
# controls.  A result query must never permit an unbounded index from an
# untrusted client, while still covering the maximum public eigenmode count.
ModeNumber = Annotated[StrictInt, Field(ge=1, le=100)]
ResultFrame = Annotated[StrictInt, Field(ge=0, le=100000)]

# SolverCalculiX analysis controls.  These aliases stay strict at the MCP
# boundary so JSON booleans/strings cannot silently become numeric solver
# settings.
EigenmodesCount = Annotated[StrictInt, Field(ge=1, le=100)]
AnalysisFrequencyHz = Annotated[
    StrictFloat, Field(ge=0.0, le=1e9), AfterValidator(_finite)
]
BucklingFactors = Annotated[StrictInt, Field(ge=1, le=100)]
BucklingAccuracy = Annotated[
    StrictFloat, Field(gt=0.0, le=1.0), AfterValidator(_finite)
]
ConnectionToleranceM = Annotated[
    StrictFloat, Field(ge=0.0, le=1e6), AfterValidator(_finite)
]
# Native ``Fem::ConstraintContact`` controls.  The public boundary uses SI
# units (metres, pascals per metre) and a dimensionless friction coefficient;
# the Addon converts stiffness values to FreeCAD's StiffnessDensity property.
ContactAdjustM = Annotated[
    StrictFloat, Field(ge=0.0, le=1e6), AfterValidator(_finite)
]
ContactNormalStiffnessPaPerM = Annotated[
    StrictFloat, Field(gt=0.0, le=1e15), AfterValidator(_finite)
]
ContactStickStiffnessPaPerM = Annotated[
    StrictFloat, Field(gt=0.0, le=1e15), AfterValidator(_finite)
]
ContactFrictionCoefficient = Annotated[
    StrictFloat, Field(gt=0.0, le=10.0), AfterValidator(_finite)
]
CyclicSectors = Annotated[StrictInt, Field(ge=2, le=1_000_000)]
ConnectedSectors = Annotated[StrictInt, Field(ge=1, le=1_000_000)]

# R3 static nonlinear controls.  FreeCAD stores all four time values as
# ``App::PropertyTime`` quantities.  The MCP contract deliberately carries SI
# seconds and converts to those native quantities in the Addon; controls stay
# finite, positive, and bounded before crossing either trust boundary.
SolverTimeSeconds = Annotated[
    StrictFloat, Field(gt=0.0, le=1e9), AfterValidator(_finite)
]
SolverIncrementsMaximum = Annotated[StrictInt, Field(ge=1, le=1_000_000)]

# CalculiX's nonlinear material object accepts true stress (SI Pa at the MCP
# boundary) and logarithmic plastic strain.  A modest point cap keeps the
# native ``YieldPoints`` list and result/job payloads bounded.
NonlinearStressPa = Annotated[
    StrictFloat, Field(gt=0.0, le=1e15), AfterValidator(_finite)
]
PlasticStrain = Annotated[
    StrictFloat, Field(ge=0.0, le=1e3), AfterValidator(_finite)
]


class StrictModel(BaseModel):
    """Base class used by every externally supplied request model."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class YieldPoint(StrictModel):
    """One bounded true-stress/logarithmic-plastic-strain point.

    Stress is supplied in pascals and converted to FreeCAD's native MPa text
    representation at the Addon boundary.  The first point must have zero
    plastic strain; sequence monotonicity is checked by the containing
    material request.
    """

    stress_pa: NonlinearStressPa
    plastic_strain: PlasticStrain


NonlinearYieldPoints = Annotated[list[YieldPoint], Field(min_length=1, max_length=64)]


class EmptyRequest(StrictModel):
    """An explicitly empty request (rather than an untyped ``dict``)."""


class StatusRequest(StrictModel):
    pass


class DocumentRequest(StrictModel):
    document_id: BoundedText | None = None
    name: OptionalText | None = None


class SelectionRequest(StrictModel):
    document_id: BoundedText | None = None


class ViewRequest(StrictModel):
    document_id: BoundedText | None = None
    orientation: Literal["front", "rear", "left", "right", "top", "bottom", "isometric"] | None = (
        None
    )
    fit: StrictBool = False


class CaptureRequest(StrictModel):
    document_id: BoundedText | None = None
    width: Annotated[StrictInt, Field(ge=16, le=8192)] = 1280
    height: Annotated[StrictInt, Field(ge=16, le=8192)] = 720
    image_format: Literal["png", "jpeg"] = "png"


class OpenRequest(StrictModel):
    """Open a document through the Addon-controlled document operation.

    ``path`` is not interpreted by this process.  The Addon applies its own
    workspace policy and never receives an arbitrary shell or Python command.
    """

    path: BoundedPath

    @field_validator("path")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if "\x00" in value or any(ord(char) < 0x20 for char in value if char not in "\t"):
            raise ValueError("path contains a control character")
        return value


class SaveRequest(StrictModel):
    document_id: BoundedText | None = None
    path: BoundedPath | None = None
    overwrite: StrictBool = False
    expected_revision: BoundedText | None = None

    @field_validator("path")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and (
            "\x00" in value or any(ord(char) < 0x20 for char in value if char != "\t")
        ):
            raise ValueError("path contains a control character")
        return value

    @model_validator(mode="after")
    def require_revision_for_overwrite(self) -> "SaveRequest":
        if self.overwrite and self.expected_revision is None:
            raise ValueError("expected_revision is required when overwrite is true")
        if self.expected_revision is not None and not self.expected_revision.isdigit():
            raise ValueError("expected_revision must be a decimal revision")
        return self


class _AnalysisOptions(StrictModel):
    """Shared SolverCalculiX analysis discriminator and variant controls."""

    analysis_type: Literal["static", "frequency", "buckling"] = "static"
    eigenmodes_count: EigenmodesCount | None = None
    frequency_low_hz: AnalysisFrequencyHz | None = None
    frequency_high_hz: AnalysisFrequencyHz | None = None
    buckling_factors: BucklingFactors | None = None
    buckling_accuracy: BucklingAccuracy | None = None

    # R3 controls are intentionally part of the static create-analysis
    # request rather than a generic native-property escape hatch.  They remain
    # optional so existing linear callers serialize exactly as before.
    geometrical_nonlinearity: Literal["linear", "nonlinear"] | None = None
    material_nonlinearity: Literal["linear", "nonlinear"] | None = None
    automatic_incrementation: StrictBool | None = None
    time_initial_increment_s: SolverTimeSeconds | None = None
    time_minimum_increment_s: SolverTimeSeconds | None = None
    time_maximum_increment_s: SolverTimeSeconds | None = None
    time_period_s: SolverTimeSeconds | None = None
    increments_maximum: SolverIncrementsMaximum | None = None

    @model_validator(mode="after")
    def validate_analysis_variant(self) -> "_AnalysisOptions":
        frequency_fields = (
            self.eigenmodes_count,
            self.frequency_low_hz,
            self.frequency_high_hz,
        )
        buckling_fields = (self.buckling_factors, self.buckling_accuracy)

        geometrical_nonlinearity = self.geometrical_nonlinearity or "linear"
        material_nonlinearity = self.material_nonlinearity or "linear"
        automatic_incrementation = (
            True if self.automatic_incrementation is None else self.automatic_incrementation
        )
        nonlinear_fields = (
            geometrical_nonlinearity,
            material_nonlinearity,
            automatic_incrementation,
            self.time_initial_increment_s,
            self.time_minimum_increment_s,
            self.time_maximum_increment_s,
            self.time_period_s,
            self.increments_maximum,
        )

        if self.analysis_type != "static":
            # Keep the mode API closed: nonlinear controls and single-step
            # time settings have no native writer representation for modal or
            # buckling jobs.
            if (
                geometrical_nonlinearity != "linear"
                or material_nonlinearity != "linear"
                or automatic_incrementation is not True
                or any(value is not None for value in nonlinear_fields[3:])
            ):
                raise ValueError("nonlinear/time controls are supported only for static analysis")

        if self.analysis_type == "static":
            if any(value is not None for value in (*frequency_fields, *buckling_fields)):
                raise ValueError("static analysis does not accept analysis-specific fields")
            self._validate_time_increments()
            return self

        if self.analysis_type == "frequency":
            if self.eigenmodes_count is None:
                raise ValueError("eigenmodes_count is required for frequency analysis")
            if (self.frequency_low_hz is None) != (self.frequency_high_hz is None):
                raise ValueError(
                    "frequency_low_hz and frequency_high_hz must be provided together"
                )
            if (
                self.frequency_low_hz is not None
                and self.frequency_high_hz is not None
                and self.frequency_high_hz <= self.frequency_low_hz
            ):
                raise ValueError("frequency_high_hz must be greater than frequency_low_hz")
            if any(value is not None for value in buckling_fields):
                raise ValueError("frequency analysis does not accept buckling fields")
            return self

        # The Literal above makes this branch buckling-only while keeping the
        # validation explicit if another variant is added in the future.
        if self.buckling_factors is None or self.buckling_accuracy is None:
            raise ValueError(
                "buckling_factors and buckling_accuracy are required for buckling analysis"
            )
        if any(value is not None for value in frequency_fields):
            raise ValueError("buckling analysis does not accept frequency fields")
        return self

    def _validate_time_increments(self) -> None:
        values = {
            "time_initial_increment_s": self.time_initial_increment_s,
            "time_minimum_increment_s": self.time_minimum_increment_s,
            "time_maximum_increment_s": self.time_maximum_increment_s,
            "time_period_s": self.time_period_s,
        }
        # Omitted values deliberately preserve FreeCAD's native defaults.  If
        # one control is supplied, require the complete tuple so both bridge
        # layers map a deterministic single-step writer payload.
        supplied = [name for name, value in values.items() if value is not None]
        if supplied and len(supplied) != len(values):
            raise ValueError("all time increment controls are required together")
        if not supplied:
            return
        initial = self.time_initial_increment_s
        minimum = self.time_minimum_increment_s
        maximum = self.time_maximum_increment_s
        period = self.time_period_s
        assert initial is not None and minimum is not None and maximum is not None and period is not None
        if minimum > initial or initial > maximum or maximum > period:
            raise ValueError(
                "time controls must satisfy minimum <= initial <= maximum <= period"
            )


class AnalysisRequest(_AnalysisOptions):
    document_id: BoundedText | None = None
    analysis_id: BoundedText | None = None
    name: OptionalText | None = None
    solver: Literal["SolverCalculiX"] = "SolverCalculiX"


def _validate_nonlinear_material_fields(
    hardening_model: str | None, yield_points: list[YieldPoint] | None
) -> None:
    if (hardening_model is None) != (yield_points is None):
        raise ValueError("hardening_model and yield_points must be provided together")
    if yield_points is None:
        return
    if yield_points[0].plastic_strain != 0.0:
        raise ValueError("yield_points first plastic_strain must be exactly 0.0")
    previous_stress = 0.0
    previous_strain = 0.0
    for point in yield_points:
        if point.stress_pa <= previous_stress:
            raise ValueError("yield_points stress_pa values must be strictly increasing")
        if point.plastic_strain < previous_strain:
            raise ValueError("yield_points plastic_strain values must be nondecreasing")
        previous_stress = point.stress_pa
        previous_strain = point.plastic_strain


class EntityRef(StrictModel):
    """A FreeCAD object and explicit subelements selected by a constraint."""

    object_name: BoundedText = Field(
        description="Exact FreeCAD object Name, for example 'Cantilever'; do not use object_id."
    )
    subelements: StringList = Field(
        description="FreeCAD subelement names such as 'Face1' or 'Edge2'; use [] for the whole object.",
    )


class MaterialRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    material_id: BoundedText | None = None
    name: OptionalText | None = None
    targets: Annotated[list[EntityRef], Field(max_length=MAX_LIST)] = Field(
        default_factory=list,
        description=(
            "Explicit Edge/Face/Solid references for this material. An empty list "
            "keeps a global material assignment."
        ),
    )
    youngs_modulus_pa: PositiveFiniteFloat | None = None
    poisson_ratio: Annotated[StrictFloat, Field(gt=-1, lt=0.5), AfterValidator(_finite)] | None = (
        None
    )
    density_kg_m3: PositiveFiniteFloat | None = None
    yield_strength_pa: PositiveFiniteFloat | None = None
    hardening_model: Literal["isotropic", "kinematic"] | None = None
    yield_points: NonlinearYieldPoints | None = None

    @model_validator(mode="after")
    def validate_nonlinear_material(self) -> "MaterialRequest":
        _validate_nonlinear_material_fields(self.hardening_model, self.yield_points)
        return self


class AmplitudePoint(StrictModel):
    """One bounded CalculiX amplitude sample.

    The wire format intentionally stays as a closed object with no name,
    kind, or extrapolation escape hatches.  Times are expressed in seconds
    and scales are dimensionless multipliers.
    """

    time_s: Annotated[
        StrictFloat,
        Field(ge=0.0, le=1e12),
        AfterValidator(_finite),
    ]
    scale: Annotated[
        StrictFloat,
        Field(ge=-1e9, le=1e9),
        AfterValidator(_finite),
    ]


Amplitude = Annotated[
    list[AmplitudePoint],
    Field(
        min_length=2,
        max_length=256,
        description=(
            "At least two samples with the first time_s exactly 0.0 and "
            "strictly increasing finite times."
        ),
    ),
]


class _AmplitudeRequestModel(StrictModel):
    """Shared optional amplitude field and sequence validation."""

    amplitude: Amplitude | None = None

    @field_validator("amplitude")
    @classmethod
    def validate_amplitude_sequence(
        cls, value: list[AmplitudePoint] | None
    ) -> list[AmplitudePoint] | None:
        if value is None:
            return None
        if value[0].time_s != 0.0:
            raise ValueError("amplitude first time_s must be exactly 0.0")
        previous = value[0].time_s
        for point in value[1:]:
            if point.time_s <= previous:
                raise ValueError("amplitude time_s values must be strictly increasing")
            previous = point.time_s
        return value


class ConstraintRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    constraint_id: BoundedText | None = None
    constraint_type: Literal[
        "fixed", "displacement", "force", "pressure", "selfweight", "plane_rotation", "transform"
    ] | None = None
    # Empty targets deliberately mean "the current GUI selection".  The Addon
    # resolves that selection on the FreeCAD main thread.
    targets: Annotated[list[EntityRef], Field(max_length=MAX_LIST)] = Field(
        default_factory=list,
        description=(
            "Entity references. Each item must contain object_name and subelements, "
            "for example [{object_name: 'Cantilever', subelements: ['Face1']}]. "
            "Leave empty to use the current FreeCAD GUI selection."
        ),
    )
    displacement_m: ValueList = Field(default_factory=list)
    force_n: ValueList = Field(default_factory=list)
    pressure_pa: ValueList = Field(default_factory=list)
    selfweight_acceleration_m_s2: ValueList = Field(default_factory=list)
    transform_type: Literal["rectangular", "cylindrical"] | None = None
    base_point_m: RemoteReferenceVector3 | None = None
    axis_m: RemoteReferenceVector3 | None = None
    rotation_rad: TransformRotationVector3 | None = None

    @model_validator(mode="after")
    def validate_plane_rotation_values(self) -> "ConstraintRequest":
        if self.constraint_type == "plane_rotation" and any(
            value
            for value in (
                self.displacement_m,
                self.force_n,
                self.pressure_pa,
                self.selfweight_acceleration_m_s2,
            )
        ):
            raise ValueError("value fields are unsupported for plane_rotation")
        if self.constraint_type == "transform":
            if not self.targets:
                raise ValueError("transform requires explicit targets")
            if self.transform_type == "rectangular":
                if self.base_point_m is not None or self.rotation_rad is None or self.axis_m is not None:
                    raise ValueError("rectangular transform requires rotation_rad only")
            elif self.transform_type == "cylindrical":
                if self.base_point_m is None or self.axis_m is None or self.rotation_rad is not None:
                    raise ValueError("cylindrical transform requires base_point_m and axis_m only")
                if math.sqrt(sum(component * component for component in self.axis_m)) <= 0.0:
                    raise ValueError("axis_m must have a non-zero norm")
            else:
                raise ValueError("transform_type is required for transform")
            if any(
                value
                for value in (
                    self.displacement_m,
                    self.force_n,
                    self.pressure_pa,
                    self.selfweight_acceleration_m_s2,
                )
            ):
                raise ValueError("value fields are unsupported for transform")
        return self


class MeshRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    element_size_mm: PositiveFiniteFloat | None = None
    second_order: StrictBool = False
    algorithm: Literal["gmsh"] = "gmsh"
    element_dimension: Literal["1d", "2d", "3d"] = "3d"
    shape_id: BoundedText | None = None


class ValidateRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    strict: StrictBool = True


class JobsRequest(StrictModel):
    analysis_id: BoundedText | None = None
    job_id: BoundedText | None = None


class ResultsRequest(StrictModel):
    analysis_id: BoundedText
    job_id: BoundedText | None = None
    field: Literal["displacement", "stress", "strain", "von_mises"] | None = None
    max_items: Annotated[StrictInt, Field(ge=1, le=10000)] = 1000
    mode: ModeNumber | None = None
    frame: ResultFrame = 0


# Dedicated public-tool inputs.  Unlike the compatibility request models above,
# these intentionally do not expose an ``action`` discriminator: each MCP tool
# maps to one safe operation and injects its fixed action at the bridge boundary.
class GetStatusRequest(StatusRequest):
    pass


class InspectDocumentRequest(StrictModel):
    document_id: BoundedText | None = None


class GetSelectionRequest(StrictModel):
    document_id: BoundedText | None = None


class SetViewRequest(StrictModel):
    document_id: BoundedText | None = None
    orientation: Literal["front", "rear", "left", "right", "top", "bottom", "isometric"] = (
        "isometric"
    )
    fit: StrictBool = False


class SetVisibilityRequest(StrictModel):
    """Change only bounded FreeCAD tree-object visibility.

    Object names are stable document identifiers returned by
    ``inspect_document``.  Global modes deliberately reject a target list,
    while targeted modes require one, keeping every call unambiguous.
    """

    document_id: BoundedText | None = None
    mode: Literal["show", "hide", "isolate", "show_all", "hide_all"]
    object_names: Annotated[list[BoundedText], Field(max_length=256)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_visibility_targets(self) -> "SetVisibilityRequest":
        targeted = self.mode in {"show", "hide", "isolate"}
        if targeted and not self.object_names:
            raise ValueError("object_names is required for targeted visibility modes")
        if not targeted and self.object_names:
            raise ValueError("object_names is not accepted for global visibility modes")
        if len(set(self.object_names)) != len(self.object_names):
            raise ValueError("object_names must not contain duplicates")
        return self


class CaptureGuiRequest(CaptureRequest):
    scope: Literal["viewport", "window"] = "viewport"


class OpenModelRequest(OpenRequest):
    pass


class SaveDocumentRequest(SaveRequest):
    pass


class CreateAnalysisRequest(_AnalysisOptions):
    document_id: BoundedText | None = None
    name: OptionalText | None = None
    solver: Literal["SolverCalculiX"] = "SolverCalculiX"


class AssignMaterialRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    material_id: BoundedText | None = None
    name: OptionalText | None = None
    targets: Annotated[list[EntityRef], Field(max_length=MAX_LIST)] = Field(
        default_factory=list,
        description=(
            "Explicit Edge/Face/Solid references for this material. An empty list "
            "keeps a global material assignment."
        ),
    )
    youngs_modulus_pa: PositiveFiniteFloat | None = None
    poisson_ratio: Annotated[StrictFloat, Field(gt=-1, lt=0.5), AfterValidator(_finite)] | None = (
        None
    )
    density_kg_m3: PositiveFiniteFloat | None = None
    yield_strength_pa: PositiveFiniteFloat | None = None
    hardening_model: Literal["isotropic", "kinematic"] | None = None
    yield_points: NonlinearYieldPoints | None = None

    @model_validator(mode="after")
    def validate_nonlinear_material(self) -> "AssignMaterialRequest":
        _validate_nonlinear_material_fields(self.hardening_model, self.yield_points)
        return self


class AddConstraintRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    constraint_type: Literal[
        "fixed", "displacement", "force", "pressure", "selfweight", "plane_rotation", "transform"
    ]
    targets: Annotated[list[EntityRef], Field(max_length=MAX_LIST)] = Field(
        default_factory=list,
        description=(
            "Entity references using object_name and subelements; e.g. "
            "[{object_name: 'Cantilever', subelements: ['Face1']}]. "
            "An empty list uses the current GUI selection."
        ),
    )
    displacement_m: ValueList = Field(default_factory=list)
    force_n: ValueList = Field(default_factory=list)
    pressure_pa: ValueList = Field(default_factory=list)
    selfweight_acceleration_m_s2: ValueList = Field(default_factory=list)
    transform_type: Literal["rectangular", "cylindrical"] | None = None
    base_point_m: RemoteReferenceVector3 | None = None
    axis_m: RemoteReferenceVector3 | None = None
    rotation_rad: TransformRotationVector3 | None = None

    @model_validator(mode="after")
    def validate_plane_rotation_values(self) -> "AddConstraintRequest":
        if self.constraint_type == "plane_rotation" and any(
            value
            for value in (
                self.displacement_m,
                self.force_n,
                self.pressure_pa,
                self.selfweight_acceleration_m_s2,
            )
        ):
            raise ValueError("value fields are unsupported for plane_rotation")
        if self.constraint_type == "transform":
            if not self.targets:
                raise ValueError("transform requires explicit targets")
            if self.transform_type == "rectangular":
                if self.base_point_m is not None or self.rotation_rad is None or self.axis_m is not None:
                    raise ValueError("rectangular transform requires rotation_rad only")
            elif self.transform_type == "cylindrical":
                if self.base_point_m is None or self.axis_m is None or self.rotation_rad is not None:
                    raise ValueError("cylindrical transform requires base_point_m and axis_m only")
                if math.sqrt(sum(component * component for component in self.axis_m)) <= 0.0:
                    raise ValueError("axis_m must have a non-zero norm")
            else:
                raise ValueError("transform_type is required for transform")
            if any(
                value
                for value in (
                    self.displacement_m,
                    self.force_n,
                    self.pressure_pa,
                    self.selfweight_acceleration_m_s2,
                )
            ):
                raise ValueError("value fields are unsupported for transform")
        return self


class AddLoadRequest(_AmplitudeRequestModel):
    """Add one typed SI load while rejecting unrelated value fields."""

    document_id: BoundedText | None = None
    analysis_id: BoundedText
    load_type: Literal["force", "pressure", "gravity", "acceleration", "centrifugal"]
    targets: Annotated[list[EntityRef], Field(max_length=MAX_LIST)] = Field(
        default_factory=list,
        description=(
            "Entity references using object_name and subelements; an empty list "
            "uses the current FreeCAD GUI selection."
        ),
    )
    force_n: FiniteFloat | None = Field(
        default=None,
        description="Force magnitude in newtons; required only for load_type='force'.",
    )
    pressure_pa: FiniteFloat | None = Field(
        default=None,
        description="Pressure magnitude in pascals; required only for load_type='pressure'.",
    )
    acceleration_m_s2: Vector3 | None = Field(
        default=None,
        description=(
            "Three global acceleration components in m/s^2; required only for "
            "load_type='gravity' or 'acceleration'."
        ),
    )
    rotation_frequency_hz: CentrifugalFrequencyHz | None = Field(
        default=None,
        description=(
            "Positive centrifugal rotation frequency in cycles per second; required "
            "only for load_type='centrifugal'."
        ),
    )
    axis: EntityRef | None = Field(
        default=None,
        description=(
            "Exactly one axis reference for load_type='centrifugal'; it must contain "
            "one EdgeN subelement."
        ),
    )

    @model_validator(mode="after")
    def validate_load_values(self) -> "AddLoadRequest":
        if self.amplitude is not None and self.load_type not in {"force", "pressure"}:
            raise ValueError("amplitude is supported only for force and pressure loads")
        if self.load_type == "force":
            if self.force_n is None:
                raise ValueError("force_n is required for load_type='force'")
            if (
                self.pressure_pa is not None
                or self.acceleration_m_s2 is not None
                or self.rotation_frequency_hz is not None
                or self.axis is not None
            ):
                raise ValueError(
                    "pressure_pa, acceleration_m_s2, rotation_frequency_hz, and axis "
                    "are not valid for force"
                )
        elif self.load_type == "pressure":
            if self.pressure_pa is None:
                raise ValueError("pressure_pa is required for load_type='pressure'")
            if (
                self.force_n is not None
                or self.acceleration_m_s2 is not None
                or self.rotation_frequency_hz is not None
                or self.axis is not None
            ):
                raise ValueError(
                    "force_n, acceleration_m_s2, rotation_frequency_hz, and axis "
                    "are not valid for pressure"
                )
        elif self.load_type in {"gravity", "acceleration"}:
            if self.acceleration_m_s2 is None:
                raise ValueError(
                    "acceleration_m_s2 is required for load_type='{}'".format(self.load_type)
                )
            if math.hypot(*self.acceleration_m_s2) <= 0.0:
                raise ValueError("acceleration_m_s2 must have non-zero magnitude")
            if (
                self.force_n is not None
                or self.pressure_pa is not None
                or self.rotation_frequency_hz is not None
                or self.axis is not None
            ):
                raise ValueError(
                    "force_n, pressure_pa, rotation_frequency_hz, and axis are not "
                    "valid for {}".format(self.load_type)
                )
        else:
            if self.rotation_frequency_hz is None:
                raise ValueError("rotation_frequency_hz is required for load_type='centrifugal'")
            if self.axis is None:
                raise ValueError("axis is required for load_type='centrifugal'")
            if len(self.axis.subelements) != 1:
                raise ValueError("axis must contain exactly one EdgeN subelement")
            subelement = self.axis.subelements[0]
            suffix = subelement[4:] if subelement.startswith("Edge") else ""
            if not suffix or not suffix.isascii() or not suffix.isdigit() or int(suffix) <= 0:
                raise ValueError("axis must contain exactly one EdgeN subelement")
            if (
                self.force_n is not None
                or self.pressure_pa is not None
                or self.acceleration_m_s2 is not None
            ):
                raise ValueError(
                    "force_n, pressure_pa, and acceleration_m_s2 are not valid for centrifugal"
                )
        return self


class AddRemoteLoadRequest(_AmplitudeRequestModel):
    """Add a global remote force/moment load at a bounded reference point."""

    document_id: BoundedText | None = None
    analysis_id: BoundedText
    targets: Annotated[list[EntityRef], Field(min_length=1, max_length=MAX_LIST)] = Field(
        description=(
            "At least one coupled-region entity reference; each item must contain "
            "object_name and subelements."
        ),
    )
    reference_point_m: RemoteReferenceVector3 = Field(
        description=(
            "Global reference-point coordinates in meters; each component must be "
            "between -1e9 and 1e9."
        ),
    )
    force_n: RemoteLoadVector3 | None = Field(
        default=None,
        description=(
            "Global force vector components in newtons; each component must be "
            "between -1e15 and 1e15."
        ),
    )
    moment_n_m: RemoteLoadVector3 | None = Field(
        default=None,
        description=(
            "Global moment vector components in newton-meters; each component must "
            "be between -1e15 and 1e15."
        ),
    )

    @field_validator("reference_point_m")
    @classmethod
    def validate_reference_point(cls, value: list[float]) -> list[float]:
        if any(abs(component) > 1e9 for component in value):
            raise ValueError("reference_point_m components must be within ±1e9 m")
        return value

    @field_validator("force_n", "moment_n_m")
    @classmethod
    def validate_remote_vector(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and any(abs(component) > 1e15 for component in value):
            raise ValueError("remote load components must be within ±1e15 SI units")
        return value

    @model_validator(mode="after")
    def require_nonzero_remote_load(self) -> "AddRemoteLoadRequest":
        force_nonzero = self.force_n is not None and any(
            component != 0.0 for component in self.force_n
        )
        moment_nonzero = self.moment_n_m is not None and any(
            component != 0.0 for component in self.moment_n_m
        )
        if not force_nonzero and not moment_nonzero:
            raise ValueError("force_n or moment_n_m must contain a non-zero component")
        return self


class AddRemoteDisplacementRequest(_AmplitudeRequestModel):
    """Add a global rigid-body displacement/rotation at a reference point."""

    document_id: BoundedText | None = None
    analysis_id: BoundedText
    targets: Annotated[list[EntityRef], Field(min_length=1, max_length=MAX_LIST)] = Field(
        description=(
            "At least one coupled-region entity reference; each item must contain "
            "object_name and subelements."
        ),
    )
    reference_point_m: RemoteReferenceVector3 = Field(
        description=(
            "Global reference-point coordinates in meters; each component must be "
            "between -1e9 and 1e9."
        ),
    )
    translation_m: RemoteDisplacementVector3 | None = Field(
        default=None,
        description=(
            "Global translation in meters. Each of the three components is either "
            "a finite constrained value (including zero) or null for Free; each "
            "numeric component is bounded to ±1e9 m."
        ),
    )
    rotation_rad: RemoteRotationVector3 | None = Field(
        default=None,
        description=(
            "Global rotation vector in radians. Each of the three components is "
            "either a finite constrained value (including zero) or null for Free; "
            "each numeric component is bounded to ±1e6 rad."
        ),
    )

    @field_validator("reference_point_m")
    @classmethod
    def validate_reference_point(cls, value: list[float]) -> list[float]:
        if any(abs(component) > 1e9 for component in value):
            raise ValueError("reference_point_m components must be within ±1e9 m")
        return value

    @field_validator("translation_m")
    @classmethod
    def validate_translation(cls, value: list[float | None] | None) -> list[float | None] | None:
        if value is not None and any(
            component is not None and abs(component) > 1e9 for component in value
        ):
            raise ValueError("translation_m components must be within ±1e9 m")
        return value

    @field_validator("rotation_rad")
    @classmethod
    def validate_rotation(cls, value: list[float | None] | None) -> list[float | None] | None:
        if value is not None and any(
            component is not None and abs(component) > 1e6 for component in value
        ):
            raise ValueError("rotation_rad components must be within ±1e6 rad")
        return value

    @model_validator(mode="after")
    def require_constrained_component(self) -> "AddRemoteDisplacementRequest":
        constrained = any(
            component is not None
            for vector in (self.translation_m, self.rotation_rad)
            if vector is not None
            for component in vector
        )
        if not constrained:
            raise ValueError("translation_m or rotation_rad must constrain a component")
        return self


class AddBoundaryConditionRequest(_AmplitudeRequestModel):
    """Add a native CalculiX-supported structural boundary condition.

    ``pin`` and ``roller`` are closed presets over the native displacement
    object.  The presets intentionally do not expose arbitrary native
    properties or general MPC coefficients.
    """

    document_id: BoundedText | None = None
    analysis_id: BoundedText
    boundary_type: Literal[
        "fixed",
        "displacement",
        "pin",
        "roller",
    ]
    targets: Annotated[list[EntityRef], Field(max_length=MAX_LIST)] = Field(
        default_factory=list,
        description=(
            "Entity references using object_name and subelements; an empty list "
            "uses the current FreeCAD GUI selection."
        ),
    )
    displacement_m: RemoteDisplacementVector3 | None = Field(
        default=None,
        description=(
            "Three prescribed displacement components in meters; each component "
            "may be null for Free and at least one component is required for "
            "boundary_type='displacement'."
        ),
    )
    rotation_rad: RemoteRotationVector3 | None = Field(
        default=None,
        description=(
            "Optional three prescribed rotation components in radians for beam "
            "boundaries; each component may be null for Free."
        ),
    )
    axis: Literal["x", "y", "z"] | None = Field(
        default=None,
        description=(
            "Cartesian normal axis for a roller support. Exactly one axis is "
            "required for boundary_type='roller'."
        ),
    )
    normal_m: Vector3 | None = Field(
        default=None,
        description=(
            "Optional unit Cartesian normal for a roller support. Only an "
            "axis-aligned normal (one component +/-1 and the others zero) is "
            "native-writer compatible."
        ),
    )

    @model_validator(mode="after")
    def validate_boundary_values(self) -> "AddBoundaryConditionRequest":
        if self.boundary_type == "fixed":
            if self.displacement_m is not None or self.rotation_rad is not None:
                raise ValueError("displacement_m/rotation_rad are not valid for boundary_type='fixed'")
            if self.amplitude is not None:
                raise ValueError("amplitude is not valid for boundary_type='fixed'")
            if self.axis is not None or self.normal_m is not None:
                raise ValueError("axis/normal_m are not valid for boundary_type='fixed'")
        elif self.boundary_type == "displacement":
            constrained = any(
                component is not None
                for vector in (self.displacement_m, self.rotation_rad)
                if vector is not None
                for component in vector
            )
            if not constrained:
                raise ValueError(
                    "displacement_m or rotation_rad must constrain a component"
                )
            if self.axis is not None or self.normal_m is not None:
                raise ValueError("axis/normal_m are not valid for boundary_type='displacement'")
        elif self.boundary_type == "roller":
            if self.displacement_m is not None or self.rotation_rad is not None or self.amplitude is not None:
                raise ValueError("displacement_m/rotation_rad are not valid for roller")
            if (self.axis is None) == (self.normal_m is None):
                raise ValueError("roller requires exactly one of axis or normal_m")
            if self.normal_m is not None:
                nonzero = [abs(component) for component in self.normal_m if component != 0.0]
                if len(nonzero) != 1 or nonzero[0] != 1.0:
                    raise ValueError("normal_m must be an axis-aligned unit vector")
        else:
            if self.displacement_m is not None or self.rotation_rad is not None or self.amplitude is not None:
                raise ValueError(
                    "displacement_m/rotation_rad/amplitude are not valid for boundary_type='{}'".format(
                        self.boundary_type
                    )
                )
            if self.axis is not None or self.normal_m is not None:
                raise ValueError(
                    "axis/normal_m are not valid for boundary_type='{}'".format(
                        self.boundary_type
                    )
                )
        return self


class AddConnectionRequest(StrictModel):
    """Closed native tie/contact/cyclic-symmetry contract for two faces.

    Contact stiffness values are SI ``Pa/m`` and friction coefficients are
    dimensionless.  They are converted to FreeCAD's native quantities by the
    Addon; arbitrary native contact properties remain intentionally absent.
    """

    document_id: BoundedText | None = None
    analysis_id: BoundedText
    connection_type: Literal["tie", "contact", "cyclic_symmetry"]
    slave: EntityRef
    master: EntityRef
    tolerance_m: ConnectionToleranceM | None = None
    adjust: StrictBool | None = None
    # ConstraintContact.SurfaceBehavior enum values exposed in a lower-case
    # wire form; the Addon maps them to native ``Hard``/``Linear``/``Tied``.
    surface_behavior: Literal["hard", "linear", "tied"] | None = None
    # Omitted means frictionless.  Keeping omission distinct from an explicit
    # ``false`` allows the bridge to preserve the legacy tie/contact payload
    # while still rejecting contact-only fields when they are supplied.
    friction: StrictBool | None = None
    friction_coefficient: ContactFrictionCoefficient | None = None
    normal_stiffness_pa_per_m: ContactNormalStiffnessPaPerM | None = None
    stick_stiffness_pa_per_m: ContactStickStiffnessPaPerM | None = None
    adjust_m: ContactAdjustM | None = None
    sectors: CyclicSectors | None = None
    connected_sectors: ConnectedSectors | None = None

    @model_validator(mode="after")
    def validate_connection_variant(self) -> "AddConnectionRequest":
        face_pattern = re.compile(r"^Face[1-9][0-9]*$")
        references = (("slave", self.slave), ("master", self.master))
        for label, reference in references:
            if len(reference.subelements) != 1 or not face_pattern.fullmatch(reference.subelements[0]):
                raise ValueError("{} must contain exactly one FaceN subelement".format(label))
        slave_face = (self.slave.object_name, self.slave.subelements[0])
        master_face = (self.master.object_name, self.master.subelements[0])
        if slave_face == master_face:
            raise ValueError("slave and master must refer to different faces")

        if self.connection_type in {"tie", "cyclic_symmetry"}:
            if self.tolerance_m is None:
                raise ValueError("tolerance_m is required for tie connections")
            if self.adjust is None:
                raise ValueError("adjust is required for tie connections")
            if any(
                value is not None
                for value in (
                    self.surface_behavior,
                    self.friction_coefficient,
                    self.normal_stiffness_pa_per_m,
                    self.stick_stiffness_pa_per_m,
                    self.adjust_m,
                )
            ) or self.friction is not None:
                raise ValueError("contact fields are not valid for tie connections")
            if self.connection_type == "cyclic_symmetry":
                if self.sectors is None:
                    raise ValueError("sectors is required for cyclic_symmetry connections")
                if self.connected_sectors is None:
                    raise ValueError(
                        "connected_sectors is required for cyclic_symmetry connections"
                    )
                if self.connected_sectors >= self.sectors:
                    raise ValueError("connected_sectors must be less than sectors")
            elif self.sectors is not None or self.connected_sectors is not None:
                raise ValueError("cyclic symmetry fields are not valid for tie connections")
        else:
            if self.surface_behavior not in {"hard", "linear", "tied"}:
                raise ValueError("surface_behavior is required for contact connections")
            if self.tolerance_m is not None or self.adjust is not None:
                raise ValueError("tolerance_m and adjust are not valid for contact connections")
            if self.sectors is not None or self.connected_sectors is not None:
                raise ValueError("cyclic symmetry fields are not valid for contact connections")
            if self.surface_behavior in {"linear", "tied"}:
                if self.normal_stiffness_pa_per_m is None:
                    raise ValueError(
                        "normal_stiffness_pa_per_m is required for linear/tied contact"
                    )
            elif self.normal_stiffness_pa_per_m is not None:
                raise ValueError(
                    "normal_stiffness_pa_per_m is only valid for linear/tied contact"
                )
            if self.friction is True:
                if self.friction_coefficient is None:
                    raise ValueError(
                        "friction_coefficient is required when friction is true"
                    )
                if self.stick_stiffness_pa_per_m is None:
                    raise ValueError(
                        "stick_stiffness_pa_per_m is required when friction is true"
                    )
            elif (
                self.friction_coefficient is not None
                or self.stick_stiffness_pa_per_m is not None
            ):
                raise ValueError(
                    "friction_coefficient and stick_stiffness_pa_per_m require friction=true"
                )
        return self


# R7.1 native beam/shell element geometry controls.  All dimensions are SI
# metres at the public boundary.  The upper bound is deliberately conservative
# so malformed model-generated values cannot create unbounded native geometry.
ElementDimensionM = Annotated[
    StrictFloat, Field(gt=0.0, le=1e6), AfterValidator(_finite)
]
ElementOffset = Annotated[
    StrictFloat, Field(ge=-1.0, le=1.0), AfterValidator(_finite)
]
ElementRotationRad = Annotated[
    StrictFloat, Field(ge=-1e6, le=1e6), AfterValidator(_finite)
]
ElementAreaM2 = Annotated[
    StrictFloat, Field(gt=0.0, le=1e6), AfterValidator(_finite)
]

_FACE_REF_PATTERN = re.compile(r"^Face[1-9][0-9]*$")
_EDGE_REF_PATTERN = re.compile(r"^Edge[1-9][0-9]*$")


def _validate_element_targets(
    targets: list[EntityRef], pattern: re.Pattern[str], label: str
) -> list[EntityRef]:
    """Require explicit, non-empty, homogeneous Face/Edge references.

    ``EntityRef`` intentionally permits an empty subelement list for legacy
    selection-based tools.  Element geometry is different: an empty list would
    mean "all elements", so R7.1 rejects it and also rejects duplicate refs.
    """

    if not targets:
        raise ValueError("targets must contain at least one explicit reference")
    seen: set[tuple[str, str]] = set()
    for target in targets:
        if not target.subelements:
            raise ValueError("targets must contain explicit subelements")
        for subelement in target.subelements:
            if pattern.fullmatch(subelement) is None:
                raise ValueError("{} targets must contain only {} references".format(label, label))
            key = (target.object_name, subelement)
            if key in seen:
                raise ValueError("targets must not contain duplicate references")
            seen.add(key)
    return targets


class AssignElementGeometryRequest(StrictModel):
    """Closed R7.1 element geometry contract.

    ``kind`` is the discriminator.  Variant-only fields are kept optional in
    the flat wire model so the single MCP tool can expose one stable argument
    surface; the model validator then enforces the same strict presence rules
    as a discriminated union and rejects even explicitly supplied ``null``
    values for unrelated dimensions.
    """

    document_id: BoundedText | None = None
    analysis_id: BoundedText
    kind: Literal["shell", "beam_section", "beam_rotation"]
    targets: Annotated[list[EntityRef], Field(min_length=1, max_length=MAX_LIST)]

    # Shell geometry (Fem::ElementGeometry2D).
    formulation: Literal["shell", "membrane"] = "shell"
    thickness_m: ElementDimensionM | None = None
    offset: ElementOffset | None = None

    # Beam section geometry (Fem::ElementGeometry1D).  Names mirror the
    # native properties while carrying explicit SI units in the public API.
    section_type: Literal[
        "rectangular", "circular", "pipe", "elliptical", "box", "truss"
    ] | None = None
    rect_width_m: ElementDimensionM | None = None
    rect_height_m: ElementDimensionM | None = None
    circ_diameter_m: ElementDimensionM | None = None
    pipe_diameter_m: ElementDimensionM | None = None
    pipe_thickness_m: ElementDimensionM | None = None
    axis1_length_m: ElementDimensionM | None = None
    axis2_length_m: ElementDimensionM | None = None
    box_width_m: ElementDimensionM | None = None
    box_height_m: ElementDimensionM | None = None
    box_t1_m: ElementDimensionM | None = None
    box_t2_m: ElementDimensionM | None = None
    box_t3_m: ElementDimensionM | None = None
    box_t4_m: ElementDimensionM | None = None
    truss_area_m2: ElementAreaM2 | None = None

    # Beam local rotation (Fem::ElementRotation1D).
    rotation_rad: ElementRotationRad | None = None

    @model_validator(mode="after")
    def validate_element_geometry(self) -> "AssignElementGeometryRequest":
        fields = {
            "formulation",
            "thickness_m",
            "offset",
            "section_type",
            "rect_width_m",
            "rect_height_m",
            "circ_diameter_m",
            "pipe_diameter_m",
            "pipe_thickness_m",
            "axis1_length_m",
            "axis2_length_m",
            "box_width_m",
            "box_height_m",
            "box_t1_m",
            "box_t2_m",
            "box_t3_m",
            "box_t4_m",
            "truss_area_m2",
            "rotation_rad",
        }
        supplied = self.model_fields_set

        if self.kind == "shell":
            _validate_element_targets(self.targets, _FACE_REF_PATTERN, "Face")
            if self.formulation not in {"shell", "membrane"}:
                raise ValueError("formulation is unsupported")
            if self.thickness_m is None:
                raise ValueError("thickness_m is required for shell geometry")
            # Omitted offset means the native/default mid-plane offset of zero.
            if self.offset is None:
                self.offset = 0.0
            allowed = {"formulation", "thickness_m", "offset"}
            invalid = supplied.intersection(fields - allowed)
            if invalid:
                raise ValueError(
                    "fields are not valid for shell geometry: {}".format(
                        ", ".join(sorted(invalid))
                    )
                )
            return self

        if self.kind == "beam_rotation":
            _validate_element_targets(self.targets, _EDGE_REF_PATTERN, "Edge")
            if self.rotation_rad is None:
                raise ValueError("rotation_rad is required for beam_rotation geometry")
            allowed = {"rotation_rad"}
            invalid = supplied.intersection(fields - allowed)
            if invalid:
                raise ValueError(
                    "fields are not valid for beam_rotation geometry: {}".format(
                        ", ".join(sorted(invalid))
                    )
                )
            return self

        # The Literal above makes this beam-section-only, while keeping the
        # validation explicit if another geometry kind is added later.
        _validate_element_targets(self.targets, _EDGE_REF_PATTERN, "Edge")
        if self.section_type is None:
            raise ValueError("section_type is required for beam_section geometry")
        if any(field in supplied for field in ("formulation", "thickness_m", "offset", "rotation_rad")):
            raise ValueError("shell/rotation fields are not valid for beam_section geometry")

        dimensions = {
            "rectangular": {"rect_width_m", "rect_height_m"},
            "circular": {"circ_diameter_m"},
            "pipe": {"pipe_diameter_m", "pipe_thickness_m"},
            "elliptical": {"axis1_length_m", "axis2_length_m"},
            "box": {
                "box_width_m",
                "box_height_m",
                "box_t1_m",
                "box_t2_m",
                "box_t3_m",
                "box_t4_m",
            },
            "truss": {"truss_area_m2"},
        }[self.section_type]
        for field in dimensions:
            if getattr(self, field) is None:
                raise ValueError("{} is required for {} beam section".format(field, self.section_type))
        invalid = supplied.intersection(fields - dimensions - {"section_type"})
        if invalid:
            raise ValueError(
                "fields are not valid for {} beam section: {}".format(
                    self.section_type, ", ".join(sorted(invalid))
                )
            )

        if self.section_type == "pipe":
            pipe_diameter = self.pipe_diameter_m
            pipe_thickness = self.pipe_thickness_m
            if pipe_diameter is None or pipe_thickness is None:
                raise ValueError("pipe diameter and thickness are required")
            if 2.0 * pipe_thickness >= pipe_diameter:
                raise ValueError("pipe thickness must be less than half the outer diameter")
        elif self.section_type == "box":
            box_width = self.box_width_m
            box_height = self.box_height_m
            box_t1 = self.box_t1_m
            box_t2 = self.box_t2_m
            box_t3 = self.box_t3_m
            box_t4 = self.box_t4_m
            if any(value is None for value in (box_width, box_height, box_t1, box_t2, box_t3, box_t4)):
                raise ValueError("box dimensions and wall thicknesses are required")
            if box_t1 + box_t3 >= box_height:
                raise ValueError("box_t1_m + box_t3_m must be less than box_height_m")
            if box_t2 + box_t4 >= box_width:
                raise ValueError("box_t2_m + box_t4_m must be less than box_width_m")
        return self


# Descriptive variant names make the discriminated contract discoverable to
# integrations without introducing a second wire endpoint.  The public tool
# accepts the flat AssignElementGeometryRequest above.
class ShellElementGeometryRequest(AssignElementGeometryRequest):
    kind: Literal["shell"] = "shell"


class BeamSectionElementGeometryRequest(AssignElementGeometryRequest):
    kind: Literal["beam_section"] = "beam_section"


class BeamRotationElementGeometryRequest(AssignElementGeometryRequest):
    kind: Literal["beam_rotation"] = "beam_rotation"


class CreateMeshRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    element_size_mm: PositiveFiniteFloat | None = None
    second_order: StrictBool = False
    element_dimension: Literal["1d", "2d", "3d"] = "3d"
    shape_id: BoundedText | None = None


class ValidateAnalysisRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    strict: StrictBool = True


class StartAnalysisRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText


class GetJobRequest(StrictModel):
    job_id: BoundedText


class ListJobsRequest(StrictModel):
    analysis_id: BoundedText | None = None


class CancelJobRequest(StrictModel):
    job_id: BoundedText


class GetResultsRequest(StrictModel):
    analysis_id: BoundedText
    field: Literal["displacement", "stress", "strain", "von_mises"] | None = None
    max_items: Annotated[StrictInt, Field(ge=1, le=10000)] = 1000
    # ``frame`` remains available for the existing static FemPostPipeline API.
    # ``mode`` selects one native modal frame.  They are mutually exclusive
    # except for the default frame=0, which keeps old callers source-compatible.
    mode: ModeNumber | None = None
    frame: ResultFrame | None = None

    @model_validator(mode="after")
    def validate_result_selector(self) -> "GetResultsRequest":
        if self.mode is not None and self.frame not in (None, 0):
            raise ValueError("mode and nonzero frame cannot be combined")
        return self


class ShowResultRequest(GetResultsRequest):
    frame: ResultFrame = 0


# Response models are intentionally modest.  Payloads from FreeCAD vary by
# object/version, so the bridge validates the envelope and keeps ``data`` as JSON
# rather than attempting to mirror every possible result object.
class ToolResponse(StrictModel):
    ok: StrictBool = True
    data: Any = None
    warnings: Annotated[list[BoundedText], Field(max_length=MAX_LIST)] = Field(default_factory=list)

    @field_validator("data")
    @classmethod
    def reject_non_finite_payload(cls, value: Any) -> Any:
        return _finite_json(value)


REQUEST_MODELS: dict[str, type[StrictModel]] = {
    "status": StatusRequest,
    "document": DocumentRequest,
    "selection": SelectionRequest,
    "view": ViewRequest,
    "capture": CaptureRequest,
    "open": OpenRequest,
    "save": SaveRequest,
    "analysis": AnalysisRequest,
    "material": MaterialRequest,
    "constraint": ConstraintRequest,
    "load": AddLoadRequest,
    "remote_load": AddRemoteLoadRequest,
    "remote_displacement": AddRemoteDisplacementRequest,
    "boundary_condition": AddBoundaryConditionRequest,
    "connection": AddConnectionRequest,
    "element_geometry": AssignElementGeometryRequest,
    "mesh": MeshRequest,
    "validate": ValidateRequest,
    "jobs": JobsRequest,
    "results": ResultsRequest,
}

PUBLIC_REQUEST_MODELS: dict[str, type[StrictModel]] = {
    "get_status": GetStatusRequest,
    "inspect_document": InspectDocumentRequest,
    "get_selection": GetSelectionRequest,
    "set_view": SetViewRequest,
    "set_visibility": SetVisibilityRequest,
    "capture_gui": CaptureGuiRequest,
    "open_model": OpenModelRequest,
    "save_document": SaveDocumentRequest,
    "create_analysis": CreateAnalysisRequest,
    "assign_material": AssignMaterialRequest,
    "assign_element_geometry": AssignElementGeometryRequest,
    "add_constraint": AddConstraintRequest,
    "add_load": AddLoadRequest,
    "add_remote_load": AddRemoteLoadRequest,
    "add_remote_displacement": AddRemoteDisplacementRequest,
    "add_boundary_condition": AddBoundaryConditionRequest,
    "add_connection": AddConnectionRequest,
    "create_mesh": CreateMeshRequest,
    "validate_analysis": ValidateAnalysisRequest,
    "start_analysis": StartAnalysisRequest,
    "get_job": GetJobRequest,
    "list_jobs": ListJobsRequest,
    "cancel_job": CancelJobRequest,
    "get_results": GetResultsRequest,
    "show_result": ShowResultRequest,
}

# Descriptive aliases used by integrations that call these objects "inputs" or
# "params".  They intentionally point at the same strict classes (no duplicate
# schemas or less-restrictive compatibility layer).
StatusInput = StatusParams = StatusRequest
DocumentInput = DocumentParams = DocumentRequest
SelectionInput = SelectionParams = SelectionRequest
ViewInput = ViewParams = ViewRequest
CaptureInput = CaptureParams = CaptureRequest
OpenInput = OpenParams = OpenRequest
SaveInput = SaveParams = SaveRequest
AnalysisInput = AnalysisParams = AnalysisRequest
MaterialInput = MaterialParams = MaterialRequest
ConstraintInput = ConstraintParams = ConstraintRequest
MeshInput = MeshParams = MeshRequest
ValidateInput = ValidateParams = ValidateRequest
JobsInput = JobsParams = JobsRequest
ResultsInput = ResultsParams = ResultsRequest
GetStatusInput = GetStatusParams = GetStatusRequest
InspectDocumentInput = InspectDocumentParams = InspectDocumentRequest
GetSelectionInput = GetSelectionParams = GetSelectionRequest
SetViewInput = SetViewParams = SetViewRequest
SetVisibilityInput = SetVisibilityParams = SetVisibilityRequest
CaptureGuiInput = CaptureGuiParams = CaptureGuiRequest
OpenModelInput = OpenModelParams = OpenModelRequest
SaveDocumentInput = SaveDocumentParams = SaveDocumentRequest
CreateAnalysisInput = CreateAnalysisParams = CreateAnalysisRequest
AssignMaterialInput = AssignMaterialParams = AssignMaterialRequest
AddConstraintInput = AddConstraintParams = AddConstraintRequest
AddLoadInput = AddLoadParams = AddLoadRequest
AddRemoteLoadInput = AddRemoteLoadParams = AddRemoteLoadRequest
AddRemoteDisplacementInput = AddRemoteDisplacementParams = AddRemoteDisplacementRequest
AddBoundaryConditionInput = AddBoundaryConditionParams = AddBoundaryConditionRequest
AddConnectionInput = AddConnectionParams = AddConnectionRequest
AssignElementGeometryInput = AssignElementGeometryParams = AssignElementGeometryRequest
# Short aliases used by clients that refer to the route payload by its bridge
# method rather than the public tool verb.
ElementGeometryRequest = ElementGeometryInput = ElementGeometryParams = AssignElementGeometryRequest
CreateMeshInput = CreateMeshParams = CreateMeshRequest
ValidateAnalysisInput = ValidateAnalysisParams = ValidateAnalysisRequest
StartAnalysisInput = StartAnalysisParams = StartAnalysisRequest
GetJobInput = GetJobParams = GetJobRequest
ListJobsInput = ListJobsParams = ListJobsRequest
CancelJobInput = CancelJobParams = CancelJobRequest
GetResultsInput = GetResultsParams = GetResultsRequest
ShowResultInput = ShowResultParams = ShowResultRequest


__all__ = [
    "AnalysisRequest",
    "AnalysisInput",
    "AnalysisParams",
    "GetStatusRequest",
    "GetStatusInput",
    "GetStatusParams",
    "InspectDocumentRequest",
    "InspectDocumentInput",
    "InspectDocumentParams",
    "GetSelectionRequest",
    "GetSelectionInput",
    "GetSelectionParams",
    "SetViewRequest",
    "SetViewInput",
    "SetViewParams",
    "SetVisibilityRequest",
    "SetVisibilityInput",
    "SetVisibilityParams",
    "CaptureGuiRequest",
    "CaptureGuiInput",
    "CaptureGuiParams",
    "OpenModelRequest",
    "OpenModelInput",
    "OpenModelParams",
    "SaveDocumentRequest",
    "SaveDocumentInput",
    "SaveDocumentParams",
    "CreateAnalysisRequest",
    "CreateAnalysisInput",
    "CreateAnalysisParams",
    "AssignMaterialRequest",
    "AssignMaterialInput",
    "AssignMaterialParams",
    "AddConstraintRequest",
    "AddConstraintInput",
    "AddConstraintParams",
    "AddLoadRequest",
    "AddLoadInput",
    "AddLoadParams",
    "AddRemoteLoadRequest",
    "AddRemoteLoadInput",
    "AddRemoteLoadParams",
    "AddRemoteDisplacementRequest",
    "AddRemoteDisplacementInput",
    "AddRemoteDisplacementParams",
    "AddBoundaryConditionRequest",
    "AddBoundaryConditionInput",
    "AddBoundaryConditionParams",
    "AddConnectionRequest",
    "AddConnectionInput",
    "AddConnectionParams",
    "AssignElementGeometryRequest",
    "AssignElementGeometryInput",
    "AssignElementGeometryParams",
    "ElementGeometryRequest",
    "ElementGeometryInput",
    "ElementGeometryParams",
    "ShellElementGeometryRequest",
    "BeamSectionElementGeometryRequest",
    "BeamRotationElementGeometryRequest",
    "CreateMeshRequest",
    "CreateMeshInput",
    "CreateMeshParams",
    "ValidateAnalysisRequest",
    "ValidateAnalysisInput",
    "ValidateAnalysisParams",
    "StartAnalysisRequest",
    "StartAnalysisInput",
    "StartAnalysisParams",
    "GetJobRequest",
    "GetJobInput",
    "GetJobParams",
    "ListJobsRequest",
    "ListJobsInput",
    "ListJobsParams",
    "CancelJobRequest",
    "CancelJobInput",
    "CancelJobParams",
    "GetResultsRequest",
    "GetResultsInput",
    "GetResultsParams",
    "ShowResultRequest",
    "ShowResultInput",
    "ShowResultParams",
    "PUBLIC_REQUEST_MODELS",
    "BoundedPath",
    "BoundedText",
    "ModeNumber",
    "ResultFrame",
    "AnalysisFrequencyHz",
    "BucklingAccuracy",
    "BucklingFactors",
    "ConnectionToleranceM",
    "ContactAdjustM",
    "ContactNormalStiffnessPaPerM",
    "ContactStickStiffnessPaPerM",
    "ContactFrictionCoefficient",
    "CaptureRequest",
    "CaptureInput",
    "CaptureParams",
    "ConstraintRequest",
    "ConstraintInput",
    "ConstraintParams",
    "DocumentRequest",
    "DocumentInput",
    "DocumentParams",
    "EntityRef",
    "ElementDimensionM",
    "ElementOffset",
    "ElementRotationRad",
    "ElementAreaM2",
    "EigenmodesCount",
    "EmptyRequest",
    "FiniteFloat",
    "JobsRequest",
    "JobsInput",
    "JobsParams",
    "MaterialRequest",
    "MaterialInput",
    "MaterialParams",
    "MeshRequest",
    "MeshInput",
    "MeshParams",
    "OpenRequest",
    "OpenInput",
    "OpenParams",
    "REQUEST_MODELS",
    "ResultsRequest",
    "ResultsInput",
    "ResultsParams",
    "SaveRequest",
    "SaveInput",
    "SaveParams",
    "SelectionRequest",
    "SelectionInput",
    "SelectionParams",
    "StatusRequest",
    "StatusInput",
    "StatusParams",
    "StrictModel",
    "ToolResponse",
    "ValidateRequest",
    "ValidateInput",
    "ValidateParams",
    "ValueList",
    "Vector3",
    "YieldPoint",
    "ViewRequest",
    "ViewInput",
    "ViewParams",
]
