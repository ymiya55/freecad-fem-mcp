"""Strict request and response models for the public MCP tool surface.

The server accepts data from an untrusted model/client.  Keeping the wire models
in one module makes the boundary auditable: unknown fields are rejected, text and
collections are bounded, and floating point values must be finite.  The Addon may
return richer payloads, but requests never contain an escape hatch for arbitrary
code, paths, resources, or processes.
"""

from __future__ import annotations

import math
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
BoundedInt = Annotated[StrictInt, Field(ge=0, le=2_147_483_647)]


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


class AnalysisRequest(StrictModel):
    document_id: BoundedText | None = None
    analysis_id: BoundedText | None = None
    name: OptionalText | None = None
    solver: Literal["SolverCalculiX"] = "SolverCalculiX"
    # ``static`` is the FreeCAD SolverCalculiX enum for the MVP.  Dynamic,
    # buckling, thermal, and electromagnetic analyses are intentionally not
    # exposed until their Addon implementations are validated.
    analysis_type: Literal["static"] = "static"


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


class CreateAnalysisRequest(StrictModel):
    document_id: BoundedText | None = None
    name: OptionalText | None = None
    solver: Literal["SolverCalculiX"] = "SolverCalculiX"
    analysis_type: Literal["static"] = "static"


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
    "ViewRequest",
    "ViewInput",
    "ViewParams",
]
