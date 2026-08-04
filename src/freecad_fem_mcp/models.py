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
CentrifugalFrequencyHz = Annotated[StrictFloat, Field(gt=0, le=1e9), AfterValidator(_finite)]
BoundedInt = Annotated[StrictInt, Field(ge=0, le=2_147_483_647)]

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


class StrictModel(BaseModel):
    """Base class used by every externally supplied request model."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


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

    @model_validator(mode="after")
    def validate_analysis_variant(self) -> "_AnalysisOptions":
        frequency_fields = (
            self.eigenmodes_count,
            self.frequency_low_hz,
            self.frequency_high_hz,
        )
        buckling_fields = (self.buckling_factors, self.buckling_accuracy)

        if self.analysis_type == "static":
            if any(value is not None for value in (*frequency_fields, *buckling_fields)):
                raise ValueError("static analysis does not accept analysis-specific fields")
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


class AnalysisRequest(_AnalysisOptions):
    document_id: BoundedText | None = None
    analysis_id: BoundedText | None = None
    name: OptionalText | None = None
    solver: Literal["SolverCalculiX"] = "SolverCalculiX"


class MaterialRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    material_id: BoundedText | None = None
    name: OptionalText | None = None
    youngs_modulus_pa: PositiveFiniteFloat | None = None
    poisson_ratio: Annotated[StrictFloat, Field(gt=-1, lt=0.5), AfterValidator(_finite)] | None = (
        None
    )
    density_kg_m3: PositiveFiniteFloat | None = None
    yield_strength_pa: PositiveFiniteFloat | None = None


class EntityRef(StrictModel):
    """A FreeCAD object and explicit subelements selected by a constraint."""

    object_name: BoundedText = Field(
        description="Exact FreeCAD object Name, for example 'Cantilever'; do not use object_id."
    )
    subelements: StringList = Field(
        description="FreeCAD subelement names such as 'Face1' or 'Edge2'; use [] for the whole object.",
    )


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
    constraint_type: Literal["fixed", "displacement", "force", "pressure", "selfweight"] | None = (
        None
    )
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


class MeshRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    element_size_mm: PositiveFiniteFloat | None = None
    second_order: StrictBool = False
    algorithm: Literal["gmsh"] = "gmsh"
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
    field: Literal["displacement", "stress", "strain", "von_mises", "reaction"] | None = None
    max_items: Annotated[StrictInt, Field(ge=1, le=10000)] = 1000


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
    youngs_modulus_pa: PositiveFiniteFloat | None = None
    poisson_ratio: Annotated[StrictFloat, Field(gt=-1, lt=0.5), AfterValidator(_finite)] | None = (
        None
    )
    density_kg_m3: PositiveFiniteFloat | None = None
    yield_strength_pa: PositiveFiniteFloat | None = None


class AddConstraintRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    constraint_type: Literal["fixed", "displacement", "force", "pressure", "selfweight"]
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
    displacement_m: Vector3 | None = Field(
        default=None,
        description=(
            "Three prescribed displacement components in meters; required only "
            "for boundary_type='displacement'."
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
            if self.displacement_m is not None:
                raise ValueError("displacement_m is not valid for boundary_type='fixed'")
            if self.amplitude is not None:
                raise ValueError("amplitude is not valid for boundary_type='fixed'")
            if self.axis is not None or self.normal_m is not None:
                raise ValueError("axis/normal_m are not valid for boundary_type='fixed'")
        elif self.boundary_type == "displacement":
            if self.displacement_m is None:
                raise ValueError("displacement_m is required for boundary_type='displacement'")
            if self.axis is not None or self.normal_m is not None:
                raise ValueError("axis/normal_m are not valid for boundary_type='displacement'")
        elif self.boundary_type == "roller":
            if self.displacement_m is not None or self.amplitude is not None:
                raise ValueError("roller supports do not accept displacement or amplitude")
            if (self.axis is None) == (self.normal_m is None):
                raise ValueError("roller requires exactly one of axis or normal_m")
            if self.normal_m is not None:
                nonzero = [abs(component) for component in self.normal_m if component != 0.0]
                if len(nonzero) != 1 or nonzero[0] != 1.0:
                    raise ValueError("normal_m must be an axis-aligned unit vector")
        else:
            if self.displacement_m is not None or self.amplitude is not None:
                raise ValueError(
                    "displacement/amplitude are not valid for boundary_type='{}'".format(
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
    """Closed tie/contact connection contract for two single-face entities."""

    document_id: BoundedText | None = None
    analysis_id: BoundedText
    connection_type: Literal["tie", "contact"]
    slave: EntityRef
    master: EntityRef
    tolerance_m: ConnectionToleranceM | None = None
    adjust: StrictBool | None = None
    surface_behavior: Literal["hard"] | None = None

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

        if self.connection_type == "tie":
            if self.tolerance_m is None:
                raise ValueError("tolerance_m is required for tie connections")
            if self.adjust is None:
                raise ValueError("adjust is required for tie connections")
            if self.surface_behavior is not None:
                raise ValueError("surface_behavior is not valid for tie connections")
        else:
            if self.surface_behavior != "hard":
                raise ValueError("surface_behavior='hard' is required for contact connections")
            if self.tolerance_m is not None or self.adjust is not None:
                raise ValueError("tolerance_m and adjust are not valid for contact connections")
        return self


class CreateMeshRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText
    element_size_mm: PositiveFiniteFloat | None = None
    second_order: StrictBool = False
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
    field: Literal["displacement", "stress", "strain", "von_mises", "reaction"] | None = None
    max_items: Annotated[StrictInt, Field(ge=1, le=10000)] = 1000


class ShowResultRequest(GetResultsRequest):
    frame: Annotated[StrictInt, Field(ge=0, le=100000)] = 0


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
    "capture_gui": CaptureGuiRequest,
    "open_model": OpenModelRequest,
    "save_document": SaveDocumentRequest,
    "create_analysis": CreateAnalysisRequest,
    "assign_material": AssignMaterialRequest,
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
    "AnalysisFrequencyHz",
    "BucklingAccuracy",
    "BucklingFactors",
    "ConnectionToleranceM",
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
    "ViewRequest",
    "ViewInput",
    "ViewParams",
]
