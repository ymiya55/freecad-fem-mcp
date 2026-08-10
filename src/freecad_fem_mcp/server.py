"""Official MCP SDK v2 stdio server for the fixed FreeCAD FEM tool surface."""

from __future__ import annotations

import inspect
import os
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt

try:  # Official MCP SDK 2.x API.
    from mcp.server.mcpserver import MCPServer as FastMCP

    try:
        from mcp_types import ToolAnnotations
    except ImportError:  # pragma: no cover - compatibility with transitional SDK builds
        from mcp.types import ToolAnnotations  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - exercised only in dependency-free tooling
    try:  # SDK 1.x fallback for source/schema tooling only.
        from mcp.server.fastmcp import FastMCP  # type: ignore[no-redef]
        from mcp.types import ToolAnnotations  # type: ignore[no-redef]
    except ImportError:
        FastMCP = None  # type: ignore[assignment,misc]
        ToolAnnotations = None  # type: ignore[assignment,misc]

from .bridge import (
    BridgeClient,
    BridgeConfig,
    BridgeError,
    LocalNdjsonTransport,
    connection_record_path,
    load_connection_record,
)
from .models import (
    AddBoundaryConditionRequest,
    AddConnectionRequest,
    AddConstraintRequest,
    AddLoadRequest,
    AddRemoteDisplacementRequest,
    AddRemoteLoadRequest,
    Amplitude,
    AnalysisFrequencyHz,
    AssignMaterialRequest,
    AssignElementGeometryRequest,
    BoundedPath,
    BoundedText,
    BucklingAccuracy,
    BucklingFactors,
    CancelJobRequest,
    CaptureGuiRequest,
    CentrifugalFrequencyHz,
    CreateAnalysisRequest,
    CreateMeshRequest,
    ElementAreaM2,
    ElementDimensionM,
    ElementOffset,
    ElementRotationRad,
    ConnectionToleranceM,
    ContactAdjustM,
    ContactFrictionCoefficient,
    ContactNormalStiffnessPaPerM,
    ContactStickStiffnessPaPerM,
    EntityRef,
    EigenmodesCount,
    FiniteFloat,
    GetJobRequest,
    GetResultsRequest,
    GetSelectionRequest,
    GetStatusRequest,
    InspectDocumentRequest,
    ListJobsRequest,
    ModeNumber,
    OptionalText,
    OpenModelRequest,
    PositiveFiniteFloat,
    RemoteLoadVector3,
    RemoteDisplacementVector3,
    RemoteReferenceVector3,
    RemoteRotationVector3,
    TransformRotationVector3,
    SaveDocumentRequest,
    SetViewRequest,
    ShowResultRequest,
    StartAnalysisRequest,
    ValueList,
    ValidateAnalysisRequest,
    Vector3,
    YieldPoint,
)

TOOL_NAMES = (
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

PUBLIC_TOOL_ACTIONS = {
    "get_status": ("status", "get"),
    "inspect_document": ("document", "active"),
    "get_selection": ("selection", "get"),
    "set_view": ("view", "set"),
    "capture_gui": ("capture", "capture"),
    "open_model": ("open", "open"),
    "save_document": ("save", "save"),
    "create_analysis": ("analysis", "create"),
    "assign_material": ("material", "assign"),
    "assign_element_geometry": ("element_geometry", "assign"),
    "add_constraint": ("constraint", "add"),
    "add_load": ("load", "add"),
    "add_remote_load": ("remote_load", "add"),
    "add_remote_displacement": ("remote_displacement", "add"),
    "add_boundary_condition": ("boundary_condition", "add"),
    "add_connection": ("connection", "add"),
    "create_mesh": ("mesh", "create"),
    "validate_analysis": ("validate", "validate"),
    "start_analysis": ("jobs", "start"),
    "get_job": ("jobs", "get"),
    "list_jobs": ("jobs", "list"),
    "cancel_job": ("jobs", "cancel"),
    "get_results": ("results", "get"),
    "show_result": ("results", "show"),
}


class _FallbackMCP:
    """Tiny contract-only stand-in used when the optional SDK is unavailable.

    Production installation always supplies ``mcp>=2``.  The stand-in keeps
    model/schema tests importable in tools that inspect source without resolving
    dependencies; calling ``run`` still gives an actionable error.
    """

    def __init__(self, name: str, instructions: str = "") -> None:
        self.name = name
        self.instructions = instructions
        self._tools: dict[str, Any] = {}

    def tool(self, *, name: str | None = None, description: str | None = None, **_: Any):
        def decorator(function: Any) -> Any:
            self._tools[name or function.__name__] = function
            return function

        return decorator

    def run(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("mcp>=2 is required to run the stdio server")


def _bridge_client_from_environment() -> BridgeClient:
    """Create the default local client without printing or exposing credentials."""

    configured_record_path = os.environ.get("FREECAD_FEM_BRIDGE_RECORD")
    watch_path = connection_record_path(configured_record_path)
    record = load_connection_record(configured_record_path)
    try:
        port = int(os.environ.get("FREECAD_FEM_BRIDGE_PORT", ""))
    except ValueError:
        port = 0
    host = os.environ.get("FREECAD_FEM_BRIDGE_HOST", "")
    token = os.environ.get("FREECAD_FEM_BRIDGE_TOKEN")
    if record is not None:
        if not host:
            host = record["host"]
        if not port:
            port = int(record["port"])
        if token is None:
            token = record["token"]
    # The default port is only used when no live connection record exists.  The
    # client remains constructible without a token so importing the server never
    # fails; each call then returns a safe authentication error.
    if not host:
        host = "127.0.0.1"
    if not port:
        port = 8765
    try:
        config = BridgeConfig(host=host, port=port)
    except ValueError:
        # A malformed environment override must not make module import print a
        # traceback.  Fall back to the known-safe loopback endpoint; auth remains
        # required for every request.
        config = BridgeConfig()
    return BridgeClient(
        LocalNdjsonTransport(config),
        token=token,
        record_path=watch_path,
    )


def _as_mapping(request: Any) -> Mapping[str, Any]:
    if hasattr(request, "model_dump"):
        values = request.model_dump(exclude_none=True)
        # Keep the shell formulation's model default local to validation.  An
        # omitted default is not a caller-supplied field, which preserves the
        # established wire shape while explicit membrane/shell values still
        # cross the bridge for the Addon to validate again.
        if isinstance(request, AssignElementGeometryRequest):
            fields_set = getattr(request, "model_fields_set", set())
            if "formulation" not in fields_set:
                values.pop("formulation", None)
        return values
    if isinstance(request, Mapping):
        return request
    raise TypeError("request must be a validated Pydantic model")


def _make_fastmcp(name: str = "FreeCAD FEM MCP") -> Any:
    if FastMCP is None:  # pragma: no cover
        return _FallbackMCP(name)
    # Avoid constructor options that have changed between SDK v1 and v2.  The
    # official v2 FastMCP constructor accepts ``name`` and ``instructions``.
    return FastMCP(
        name=name,
        instructions=(
            "Safe FreeCAD FEM bridge. SolverCalculiX static linear workflows only; "
            "operations are restricted to the documented tools."
        ),
    )


def _register_tools(app: Any, client: BridgeClient) -> Any:
    """Register exactly the fixed tool surface on a FastMCP instance."""

    async def invoke(method: str, action: str, request: Any) -> Any:
        params = dict(_as_mapping(request))
        # Actions are injected by this wrapper and never exposed as a free-form
        # discriminator to the model/client.
        params["action"] = action
        try:
            async_call = getattr(client, "call_async", None)
            if async_call is not None:
                result = async_call(method, params)
                if inspect.isawaitable(result):
                    result = await result
            else:
                result = client.call(method, params)
        except BridgeError as exc:
            # Return a protocol-safe error object.  ``str(exc)`` is intentionally
            # limited by BridgeClient and never contains the auth token.
            return {"ok": False, "error": str(exc), "method": method}
        if inspect.isawaitable(result):  # defensive for unusual fake clients
            result = await result
        return result

    def ann(*, readonly: bool, destructive: bool, idempotent: bool = False) -> Any:
        if ToolAnnotations is None:
            return None
        return ToolAnnotations(
            readOnlyHint=readonly,
            destructiveHint=destructive,
            idempotentHint=idempotent,
        )

    @app.tool(
        name="get_status",
        description="Get FreeCAD and bridge status.",
        annotations=ann(readonly=True, destructive=False, idempotent=True),
    )
    async def get_status() -> Any:
        request = GetStatusRequest()
        return await invoke("status", "get", request)

    @app.tool(
        name="inspect_document",
        description="Inspect the active FreeCAD document.",
        annotations=ann(readonly=True, destructive=False, idempotent=True),
    )
    async def inspect_document(document_id: BoundedText | None = None) -> Any:
        request = InspectDocumentRequest(document_id=document_id)
        return await invoke("document", "active", request)

    @app.tool(
        name="get_selection",
        description="Read the current FreeCAD selection.",
        annotations=ann(readonly=True, destructive=False, idempotent=True),
    )
    async def get_selection(
        document_id: BoundedText | None = None,
    ) -> Any:
        request = GetSelectionRequest(document_id=document_id)
        return await invoke("selection", "get", request)

    @app.tool(
        name="set_view",
        description="Set the bounded FreeCAD GUI view.",
        annotations=ann(readonly=False, destructive=False, idempotent=True),
    )
    async def set_view(
        document_id: BoundedText | None = None,
        orientation: Literal[
            "front", "rear", "left", "right", "top", "bottom", "isometric"
        ] = "isometric",
        fit: StrictBool = False,
    ) -> Any:
        request = SetViewRequest(
            document_id=document_id,
            orientation=orientation,
            fit=fit,
        )
        return await invoke("view", "set", request)

    @app.tool(
        name="capture_gui",
        description="Capture a bounded GUI viewport image.",
        annotations=ann(readonly=True, destructive=False, idempotent=True),
    )
    async def capture_gui(
        document_id: BoundedText | None = None,
        width: Annotated[StrictInt, Field(ge=16, le=8192)] = 1280,
        height: Annotated[StrictInt, Field(ge=16, le=8192)] = 720,
        image_format: Literal["png", "jpeg"] = "png",
        scope: Literal["viewport", "window"] = "viewport",
    ) -> Any:
        request = CaptureGuiRequest(
            document_id=document_id,
            width=width,
            height=height,
            image_format=image_format,
            scope=scope,
        )
        return await invoke("capture", "capture", request)

    @app.tool(
        name="open_model",
        description="Open a model through Addon path policy.",
        annotations=ann(readonly=False, destructive=False, idempotent=True),
    )
    async def open_model(path: BoundedPath) -> Any:
        request = OpenModelRequest(path=path)
        return await invoke("open", "open", request)

    @app.tool(
        name="save_document",
        description="Save a document through Addon path policy.",
        annotations=ann(readonly=False, destructive=True, idempotent=True),
    )
    async def save_document(
        document_id: BoundedText | None = None,
        path: BoundedPath | None = None,
        overwrite: StrictBool = False,
        expected_revision: BoundedText | None = None,
    ) -> Any:
        request = SaveDocumentRequest(
            document_id=document_id,
            path=path,
            overwrite=overwrite,
            expected_revision=expected_revision,
        )
        return await invoke("save", "save", request)

    @app.tool(
        name="create_analysis",
        description="Create a SolverCalculiX static, frequency, or buckling analysis.",
        annotations=ann(readonly=False, destructive=False),
    )
    async def create_analysis(
        document_id: BoundedText | None = None,
        name: OptionalText | None = None,
        solver: Literal["SolverCalculiX"] = "SolverCalculiX",
        analysis_type: Literal["static", "frequency", "buckling"] = "static",
        eigenmodes_count: EigenmodesCount | None = None,
        frequency_low_hz: AnalysisFrequencyHz | None = None,
        frequency_high_hz: AnalysisFrequencyHz | None = None,
        buckling_factors: BucklingFactors | None = None,
        buckling_accuracy: BucklingAccuracy | None = None,
        geometrical_nonlinearity: Literal["linear", "nonlinear"] | None = None,
        material_nonlinearity: Literal["linear", "nonlinear"] | None = None,
        automatic_incrementation: StrictBool | None = None,
        time_initial_increment_s: Annotated[StrictFloat, Field(gt=0.0, le=1e9)] | None = None,
        time_minimum_increment_s: Annotated[StrictFloat, Field(gt=0.0, le=1e9)] | None = None,
        time_maximum_increment_s: Annotated[StrictFloat, Field(gt=0.0, le=1e9)] | None = None,
        time_period_s: Annotated[StrictFloat, Field(gt=0.0, le=1e9)] | None = None,
        increments_maximum: Annotated[StrictInt, Field(ge=1, le=1_000_000)] | None = None,
    ) -> Any:
        request = CreateAnalysisRequest(
            document_id=document_id,
            name=name,
            solver=solver,
            analysis_type=analysis_type,
            eigenmodes_count=eigenmodes_count,
            frequency_low_hz=frequency_low_hz,
            frequency_high_hz=frequency_high_hz,
            buckling_factors=buckling_factors,
            buckling_accuracy=buckling_accuracy,
            geometrical_nonlinearity=geometrical_nonlinearity,
            material_nonlinearity=material_nonlinearity,
            automatic_incrementation=automatic_incrementation,
            time_initial_increment_s=time_initial_increment_s,
            time_minimum_increment_s=time_minimum_increment_s,
            time_maximum_increment_s=time_maximum_increment_s,
            time_period_s=time_period_s,
            increments_maximum=increments_maximum,
        )
        return await invoke("analysis", "create", request)

    @app.tool(
        name="assign_material",
        description="Assign a bounded linear material.",
        annotations=ann(readonly=False, destructive=False, idempotent=True),
    )
    async def assign_material(
        analysis_id: BoundedText,
        document_id: BoundedText | None = None,
        material_id: BoundedText | None = None,
        name: OptionalText | None = None,
        targets: Annotated[
            list[EntityRef],
            Field(
                max_length=128,
                description=(
                    "Explicit Edge/Face/Solid material regions. Use [] for a global material."
                ),
            ),
        ]
        | None = None,
        youngs_modulus_pa: PositiveFiniteFloat | None = None,
        poisson_ratio: FiniteFloat | None = None,
        density_kg_m3: PositiveFiniteFloat | None = None,
        yield_strength_pa: PositiveFiniteFloat | None = None,
        hardening_model: Literal["isotropic", "kinematic"] | None = None,
        yield_points: Annotated[list[YieldPoint], Field(min_length=1, max_length=64)] | None = None,
    ) -> Any:
        request = AssignMaterialRequest(
            analysis_id=analysis_id,
            document_id=document_id,
            material_id=material_id,
            name=name,
            targets=targets or [],
            youngs_modulus_pa=youngs_modulus_pa,
            poisson_ratio=poisson_ratio,
            density_kg_m3=density_kg_m3,
            yield_strength_pa=yield_strength_pa,
            hardening_model=hardening_model,
            yield_points=yield_points,
        )
        return await invoke("material", "assign", request)

    @app.tool(
        name="assign_element_geometry",
        description=(
            "Assign closed native shell, beam-section, or beam-rotation geometry. "
            "Targets must be explicit FaceN references for shell geometry or "
            "EdgeN references for beam geometry; whole-object and empty targets "
            "are not accepted. Beam dimensions are SI metres. Shell formulation "
            "defaults to shell; membrane selects the native membrane formulation."
        ),
        annotations=ann(readonly=False, destructive=False, idempotent=True),
    )
    async def assign_element_geometry(
        analysis_id: BoundedText,
        kind: Literal["shell", "beam_section", "beam_rotation"],
        targets: Annotated[
            list[EntityRef],
            Field(
                min_length=1,
                max_length=128,
                description=(
                    "Explicit EntityRef targets. Shell uses FaceN subelements; "
                    "beam section/rotation uses EdgeN subelements."
                ),
            ),
        ],
        formulation: Literal["shell", "membrane"] | None = None,
        document_id: BoundedText | None = None,
        thickness_m: ElementDimensionM | None = None,
        offset: ElementOffset | None = None,
        section_type: Literal[
            "rectangular", "circular", "pipe", "elliptical", "box", "truss"
        ]
        | None = None,
        rect_width_m: ElementDimensionM | None = None,
        rect_height_m: ElementDimensionM | None = None,
        circ_diameter_m: ElementDimensionM | None = None,
        pipe_diameter_m: ElementDimensionM | None = None,
        pipe_thickness_m: ElementDimensionM | None = None,
        axis1_length_m: ElementDimensionM | None = None,
        axis2_length_m: ElementDimensionM | None = None,
        box_width_m: ElementDimensionM | None = None,
        box_height_m: ElementDimensionM | None = None,
        box_t1_m: ElementDimensionM | None = None,
        box_t2_m: ElementDimensionM | None = None,
        box_t3_m: ElementDimensionM | None = None,
        box_t4_m: ElementDimensionM | None = None,
        truss_area_m2: ElementAreaM2 | None = None,
        rotation_rad: ElementRotationRad | None = None,
    ) -> Any:
        # Preserve omitted variant fields when constructing the strict flat
        # request model.  This lets its discriminator validator distinguish a
        # genuinely supplied unrelated dimension from an omitted optional arg.
        payload: dict[str, Any] = {
            "analysis_id": analysis_id,
            "kind": kind,
            "targets": targets,
        }
        if document_id is not None:
            payload["document_id"] = document_id
        for name, value in (
            ("formulation", formulation),
            ("thickness_m", thickness_m),
            ("offset", offset),
            ("section_type", section_type),
            ("rect_width_m", rect_width_m),
            ("rect_height_m", rect_height_m),
            ("circ_diameter_m", circ_diameter_m),
            ("pipe_diameter_m", pipe_diameter_m),
            ("pipe_thickness_m", pipe_thickness_m),
            ("axis1_length_m", axis1_length_m),
            ("axis2_length_m", axis2_length_m),
            ("box_width_m", box_width_m),
            ("box_height_m", box_height_m),
            ("box_t1_m", box_t1_m),
            ("box_t2_m", box_t2_m),
            ("box_t3_m", box_t3_m),
            ("box_t4_m", box_t4_m),
            ("truss_area_m2", truss_area_m2),
            ("rotation_rad", rotation_rad),
        ):
            if value is not None:
                payload[name] = value
        request = AssignElementGeometryRequest(**payload)
        return await invoke("element_geometry", "assign", request)

    @app.tool(
        name="add_constraint",
        description=(
            "Add a bounded analysis constraint. Use targets with exact FreeCAD "
            "object_name and subelements, for example "
            "[{object_name: 'Cantilever', subelements: ['Face1']}]. "
            "Leave targets empty to use the current GUI selection; never use object_id. "
            "plane_rotation is a native CalculiX *MPC,PLANE coplanarity constraint "
            "over referenced mesh nodes, not a frictionless or symmetry support. "
            "ConstraintTransform rectangular uses an axis-angle rotation vector; "
            "cylindrical uses base_point_m plus a non-zero axis_m."
        ),
        annotations=ann(readonly=False, destructive=False),
    )
    async def add_constraint(
        analysis_id: BoundedText,
        constraint_type: Literal[
            "fixed", "displacement", "force", "pressure", "selfweight", "plane_rotation", "transform"
        ],
        document_id: BoundedText | None = None,
        targets: Annotated[
            list[EntityRef],
            Field(
                max_length=128,
                description=(
                    "Each item must be {object_name, subelements}; example "
                    "{object_name: 'Cantilever', subelements: ['Face1']}. "
                    "Use [] for current GUI selection."
                ),
            ),
        ]
        | None = None,
        displacement_m: ValueList | None = None,
        force_n: ValueList | None = None,
        pressure_pa: ValueList | None = None,
        selfweight_acceleration_m_s2: ValueList | None = None,
        transform_type: Literal["rectangular", "cylindrical"] | None = None,
        base_point_m: RemoteReferenceVector3 | None = None,
        axis_m: RemoteReferenceVector3 | None = None,
        rotation_rad: TransformRotationVector3 | None = None,
    ) -> Any:
        request = AddConstraintRequest(
            analysis_id=analysis_id,
            constraint_type=constraint_type,
            document_id=document_id,
            targets=targets or [],
            displacement_m=displacement_m or [],
            force_n=force_n or [],
            pressure_pa=pressure_pa or [],
            selfweight_acceleration_m_s2=selfweight_acceleration_m_s2 or [],
            transform_type=transform_type,
            base_point_m=base_point_m,
            axis_m=axis_m,
            rotation_rad=rotation_rad,
        )
        return await invoke("constraint", "add", request)

    @app.tool(
        name="add_load",
        description=(
            "Add a typed SI load. Use force_n for force, pressure_pa for pressure, "
            "exactly three acceleration_m_s2 components for gravity or arbitrary "
            "acceleration, or rotation_frequency_hz plus one EdgeN axis reference "
            "for centrifugal load. Optional amplitude is a bounded time/scale "
            "table and is supported only for force and pressure. Targets may be "
            "empty to use the current GUI selection (or all elements for centrifugal load)."
        ),
        annotations=ann(readonly=False, destructive=False),
    )
    async def add_load(
        analysis_id: BoundedText,
        load_type: Literal["force", "pressure", "gravity", "acceleration", "centrifugal"],
        document_id: BoundedText | None = None,
        targets: Annotated[
            list[EntityRef],
            Field(
                max_length=128,
                description=(
                    "Each item must be {object_name, subelements}; use [] for "
                    "the current GUI selection."
                ),
            ),
        ]
        | None = None,
        force_n: FiniteFloat | None = None,
        pressure_pa: FiniteFloat | None = None,
        acceleration_m_s2: Vector3 | None = None,
        rotation_frequency_hz: CentrifugalFrequencyHz | None = None,
        axis: EntityRef | None = None,
        amplitude: Amplitude | None = None,
    ) -> Any:
        request = AddLoadRequest(
            analysis_id=analysis_id,
            load_type=load_type,
            document_id=document_id,
            targets=targets or [],
            force_n=force_n,
            pressure_pa=pressure_pa,
            acceleration_m_s2=acceleration_m_s2,
            rotation_frequency_hz=rotation_frequency_hz,
            axis=axis,
            amplitude=amplitude,
        )
        return await invoke("load", "add", request)

    @app.tool(
        name="add_remote_load",
        description=(
            "Add a remote global force and/or moment at a reference point. Targets "
            "must identify at least one coupled region; reference_point_m is in "
            "global meters, force_n in global newtons, and moment_n_m in global "
            "newton-meters. Optional amplitude is a bounded time/scale table. "
            "At least one load vector must be non-zero."
        ),
        annotations=ann(readonly=False, destructive=False),
    )
    async def add_remote_load(
        analysis_id: BoundedText,
        targets: Annotated[
            list[EntityRef],
            Field(
                min_length=1,
                max_length=128,
                description=(
                    "At least one coupled-region entity reference; each item must "
                    "contain object_name and subelements."
                ),
            ),
        ],
        reference_point_m: RemoteReferenceVector3,
        document_id: BoundedText | None = None,
        force_n: RemoteLoadVector3 | None = None,
        moment_n_m: RemoteLoadVector3 | None = None,
        amplitude: Amplitude | None = None,
    ) -> Any:
        request = AddRemoteLoadRequest(
            analysis_id=analysis_id,
            targets=targets,
            reference_point_m=reference_point_m,
            document_id=document_id,
            force_n=force_n,
            moment_n_m=moment_n_m,
            amplitude=amplitude,
        )
        return await invoke("remote_load", "add", request)

    @app.tool(
        name="add_remote_displacement",
        description=(
            "Add a remote global displacement and/or rotation at a reference point. "
            "Targets must identify at least one coupled region; reference_point_m "
            "is in global meters, translation_m in global meters, and rotation_rad "
            "in global radians. Each numeric component constrains that DOF (including "
            "zero); null means Free. Optional amplitude is a bounded time/scale "
            "table. At least one component must be numeric."
        ),
        annotations=ann(readonly=False, destructive=False),
    )
    async def add_remote_displacement(
        analysis_id: BoundedText,
        targets: Annotated[
            list[EntityRef],
            Field(
                min_length=1,
                max_length=128,
                description=(
                    "At least one coupled-region entity reference; each item must "
                    "contain object_name and subelements."
                ),
            ),
        ],
        reference_point_m: RemoteReferenceVector3,
        document_id: BoundedText | None = None,
        translation_m: RemoteDisplacementVector3 | None = None,
        rotation_rad: RemoteRotationVector3 | None = None,
        amplitude: Amplitude | None = None,
    ) -> Any:
        request = AddRemoteDisplacementRequest(
            analysis_id=analysis_id,
            targets=targets,
            reference_point_m=reference_point_m,
            document_id=document_id,
            translation_m=translation_m,
            rotation_rad=rotation_rad,
            amplitude=amplitude,
        )
        return await invoke("remote_displacement", "add", request)

    @app.tool(
        name="add_boundary_condition",
        description=(
            "Add a native fixed, prescribed-displacement, pin, or roller "
            "boundary condition. Fixed/preset "
            "conditions take no displacement/rotation; displacement accepts "
            "nullable displacement_m and rotation_rad vectors, with at least "
            "one constrained component. Roller requires an axis or axis-aligned normal_m. "
            "Optional amplitude is supported "
            "only for prescribed displacement. Targets may be empty to use "
            "the current GUI selection."
        ),
        annotations=ann(readonly=False, destructive=False),
    )
    async def add_boundary_condition(
        analysis_id: BoundedText,
        boundary_type: Literal[
            "fixed",
            "displacement",
            "pin",
            "roller",
        ],
        document_id: BoundedText | None = None,
        targets: Annotated[
            list[EntityRef],
            Field(
                max_length=128,
                description=(
                    "Each item must be {object_name, subelements}; use [] for "
                    "the current GUI selection."
                ),
            ),
        ]
        | None = None,
        displacement_m: RemoteDisplacementVector3 | None = None,
        rotation_rad: RemoteRotationVector3 | None = None,
        axis: Literal["x", "y", "z"] | None = None,
        normal_m: Vector3 | None = None,
        amplitude: Amplitude | None = None,
    ) -> Any:
        request = AddBoundaryConditionRequest(
            analysis_id=analysis_id,
            boundary_type=boundary_type,
            document_id=document_id,
            targets=targets or [],
            displacement_m=displacement_m,
            rotation_rad=rotation_rad,
            axis=axis,
            normal_m=normal_m,
            amplitude=amplitude,
        )
        return await invoke("boundary_condition", "add", request)

    @app.tool(
        name="add_connection",
        description=(
            "Add a bounded tie, cyclic-symmetry tie, or native CalculiX contact connection between exactly one "
            "slave FaceN and one master FaceN. Tie connections require finite "
            "tolerance_m (0..1e6 m) and adjust; cyclic_symmetry additionally "
            "requires sectors>=2 and 1<=connected_sectors<sectors. Contact supports "
            "surface_behavior='hard'|'linear'|'tied'; linear/tied require positive "
            "normal_stiffness_pa_per_m (SI Pa/m). Set friction=true to provide a "
            "dimensionless friction_coefficient and positive stick_stiffness_pa_per_m "
            "(SI Pa/m). adjust_m is an optional SI metre clearance. Thermal, shell, "
            "multi-face, autopair, arbitrary native properties, and custom axis "
            "placements are not supported."
        ),
        annotations=ann(readonly=False, destructive=False),
    )
    async def add_connection(
        analysis_id: BoundedText,
        connection_type: Literal["tie", "contact", "cyclic_symmetry"],
        slave: EntityRef,
        master: EntityRef,
        document_id: BoundedText | None = None,
        tolerance_m: ConnectionToleranceM | None = None,
        adjust: StrictBool | None = None,
        surface_behavior: Literal["hard", "linear", "tied"] | None = None,
        friction: StrictBool | None = None,
        friction_coefficient: ContactFrictionCoefficient | None = None,
        normal_stiffness_pa_per_m: ContactNormalStiffnessPaPerM | None = None,
        stick_stiffness_pa_per_m: ContactStickStiffnessPaPerM | None = None,
        adjust_m: ContactAdjustM | None = None,
        sectors: Annotated[StrictInt, Field(ge=2, le=1_000_000)] | None = None,
        connected_sectors: Annotated[StrictInt, Field(ge=1, le=1_000_000)] | None = None,
    ) -> Any:
        request = AddConnectionRequest(
            analysis_id=analysis_id,
            connection_type=connection_type,
            slave=slave,
            master=master,
            document_id=document_id,
            tolerance_m=tolerance_m,
            adjust=adjust,
            surface_behavior=surface_behavior,
            friction=friction,
            friction_coefficient=friction_coefficient,
            normal_stiffness_pa_per_m=normal_stiffness_pa_per_m,
            stick_stiffness_pa_per_m=stick_stiffness_pa_per_m,
            adjust_m=adjust_m,
            sectors=sectors,
            connected_sectors=connected_sectors,
        )
        return await invoke("connection", "add", request)

    @app.tool(
        name="create_mesh",
        description=(
            "Create a Gmsh analysis mesh. element_dimension selects the closed "
            "1d, 2d, or 3d native element path and defaults to 3d."
        ),
        annotations=ann(readonly=False, destructive=False),
    )
    async def create_mesh(
        analysis_id: BoundedText,
        document_id: BoundedText | None = None,
        element_size_mm: PositiveFiniteFloat | None = None,
        second_order: StrictBool = False,
        element_dimension: Literal["1d", "2d", "3d"] = "3d",
        shape_id: BoundedText | None = None,
    ) -> Any:
        request = CreateMeshRequest(
            analysis_id=analysis_id,
            document_id=document_id,
            element_size_mm=element_size_mm,
            second_order=second_order,
            element_dimension=element_dimension,
            shape_id=shape_id,
        )
        return await invoke("mesh", "create", request)

    @app.tool(
        name="validate_analysis",
        description="Validate a static analysis before solving.",
        annotations=ann(readonly=True, destructive=False, idempotent=True),
    )
    async def validate_analysis(
        analysis_id: BoundedText,
        document_id: BoundedText | None = None,
        strict: StrictBool = True,
    ) -> Any:
        request = ValidateAnalysisRequest(
            analysis_id=analysis_id,
            document_id=document_id,
            strict=strict,
        )
        return await invoke("validate", "validate", request)

    @app.tool(
        name="start_analysis",
        description="Start a SolverCalculiX analysis job.",
        annotations=ann(readonly=False, destructive=True),
    )
    async def start_analysis(
        analysis_id: BoundedText,
        document_id: BoundedText | None = None,
    ) -> Any:
        request = StartAnalysisRequest(
            analysis_id=analysis_id,
            document_id=document_id,
        )
        return await invoke("jobs", "start", request)

    @app.tool(
        name="get_job",
        description="Inspect one solver job.",
        annotations=ann(readonly=True, destructive=False, idempotent=True),
    )
    async def get_job(job_id: BoundedText) -> Any:
        request = GetJobRequest(job_id=job_id)
        return await invoke("jobs", "get", request)

    @app.tool(
        name="list_jobs",
        description="List bounded solver jobs.",
        annotations=ann(readonly=True, destructive=False, idempotent=True),
    )
    async def list_jobs(analysis_id: BoundedText | None = None) -> Any:
        request = ListJobsRequest(analysis_id=analysis_id)
        return await invoke("jobs", "list", request)

    @app.tool(
        name="cancel_job",
        description="Cancel one solver job.",
        annotations=ann(readonly=False, destructive=True),
    )
    async def cancel_job(job_id: BoundedText) -> Any:
        request = CancelJobRequest(job_id=job_id)
        return await invoke("jobs", "cancel", request)

    @app.tool(
        name="get_results",
        description=(
            "Read bounded SolverCalculiX results. Static analyses use the "
            "FemPostPipeline frame; frequency/buckling analyses may select a "
            "native ResultMechanical mode number."
        ),
        annotations=ann(readonly=True, destructive=False, idempotent=True),
    )
    async def get_results(
        analysis_id: BoundedText,
        field: Literal["displacement", "stress", "strain", "von_mises", "reaction"] | None = None,
        max_items: Annotated[StrictInt, Field(ge=1, le=10000)] = 1000,
        mode: ModeNumber | None = None,
        frame: Annotated[StrictInt, Field(ge=0, le=100000)] | None = None,
    ) -> Any:
        request = GetResultsRequest(
            analysis_id=analysis_id,
            field=field,
            max_items=max_items,
            mode=mode,
            frame=frame,
        )
        return await invoke("results", "get", request)

    @app.tool(
        name="show_result",
        description=(
            "Show one bounded result field in FreeCAD. Use mode for a native "
            "frequency/buckling Eigenmode and frame for a pipeline frame."
        ),
        annotations=ann(readonly=False, destructive=False, idempotent=True),
    )
    async def show_result(
        analysis_id: BoundedText,
        field: Literal["displacement", "stress", "strain", "von_mises", "reaction"] | None = None,
        max_items: Annotated[StrictInt, Field(ge=1, le=10000)] = 1000,
        frame: Annotated[StrictInt, Field(ge=0, le=100000)] = 0,
        mode: ModeNumber | None = None,
    ) -> Any:
        request = ShowResultRequest(
            analysis_id=analysis_id,
            field=field,
            max_items=max_items,
            frame=frame,
            mode=mode,
        )
        return await invoke("results", "show", request)

    # MCP SDK 2.0's argument model intentionally defaults to ``extra=ignore``
    # for broad backwards compatibility.  Our public contract is stricter: mark
    # every advertised direct-field schema as closed so clients cannot infer an
    # open-ended escape hatch.  Nested Pydantic models already carry the same
    # ``additionalProperties: false`` constraint.
    manager = getattr(app, "_tool_manager", None)
    registered = getattr(manager, "_tools", None)
    if isinstance(registered, Mapping):
        for tool in registered.values():
            parameters = getattr(tool, "parameters", None)
            if isinstance(parameters, dict):
                parameters["additionalProperties"] = False

    return app


def create_server(client: BridgeClient | None = None, *, name: str = "FreeCAD FEM MCP") -> Any:
    """Build a server with an injectable bridge client for tests and Addon use."""

    app = _make_fastmcp(name)
    return _register_tools(app, client or _bridge_client_from_environment())


def get_tool_names(app: Any | None = None) -> tuple[str, ...]:
    """Return the contract names without relying on private SDK internals."""

    if app is None:
        return TOOL_NAMES
    # FastMCP v2 exposes ``_tool_manager``; this fallback keeps the contract useful
    # for lightweight test doubles without importing internal SDK types.
    manager = getattr(app, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    if tools is None:
        tools = getattr(app, "_tools", None)
    if isinstance(tools, Mapping):
        return tuple(tools)
    return TOOL_NAMES


# The module-level app is intentionally created without making a bridge request.
# MCP clients commonly import ``mcp`` to inspect its contract before starting it.
mcp = create_server()


def run_stdio(app: Any | None = None) -> None:
    """Run the official MCP stdio transport, keeping stdout protocol-clean."""

    server = app or mcp
    # FastMCP owns the stdio framing in SDK v2.  No application message is ever
    # printed to stdout; diagnostics belong to the SDK's stderr logger.
    server.run(transport="stdio")


def main() -> None:
    run_stdio()


build_server = create_server
run = run_stdio


__all__ = [
    "PUBLIC_TOOL_ACTIONS",
    "TOOL_NAMES",
    "create_server",
    "build_server",
    "get_tool_names",
    "main",
    "mcp",
    "run_stdio",
    "run",
]
