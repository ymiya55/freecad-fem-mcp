"""Official MCP SDK v2 stdio server for the fixed FreeCAD FEM tool surface."""

from __future__ import annotations

import inspect
import os
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictInt

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
    AddConstraintRequest,
    AddLoadRequest,
    AddRemoteDisplacementRequest,
    AddRemoteLoadRequest,
    AssignMaterialRequest,
    BoundedPath,
    BoundedText,
    CancelJobRequest,
    CaptureGuiRequest,
    CentrifugalFrequencyHz,
    CreateAnalysisRequest,
    CreateMeshRequest,
    EntityRef,
    FiniteFloat,
    GetJobRequest,
    GetResultsRequest,
    GetSelectionRequest,
    GetStatusRequest,
    InspectDocumentRequest,
    ListJobsRequest,
    OptionalText,
    OpenModelRequest,
    PositiveFiniteFloat,
    RemoteLoadVector3,
    RemoteDisplacementVector3,
    RemoteReferenceVector3,
    RemoteRotationVector3,
    SaveDocumentRequest,
    SetViewRequest,
    ShowResultRequest,
    StartAnalysisRequest,
    ValueList,
    ValidateAnalysisRequest,
    Vector3,
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
    "add_constraint",
    "add_load",
    "add_remote_load",
    "add_remote_displacement",
    "add_boundary_condition",
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
    "add_constraint": ("constraint", "add"),
    "add_load": ("load", "add"),
    "add_remote_load": ("remote_load", "add"),
    "add_remote_displacement": ("remote_displacement", "add"),
    "add_boundary_condition": ("boundary_condition", "add"),
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
        return request.model_dump(exclude_none=True)
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
        description="Create a SolverCalculiX static analysis.",
        annotations=ann(readonly=False, destructive=False),
    )
    async def create_analysis(
        document_id: BoundedText | None = None,
        name: OptionalText | None = None,
        solver: Literal["SolverCalculiX"] = "SolverCalculiX",
        analysis_type: Literal["static"] = "static",
    ) -> Any:
        request = CreateAnalysisRequest(
            document_id=document_id,
            name=name,
            solver=solver,
            analysis_type=analysis_type,
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
        youngs_modulus_pa: PositiveFiniteFloat | None = None,
        poisson_ratio: FiniteFloat | None = None,
        density_kg_m3: PositiveFiniteFloat | None = None,
        yield_strength_pa: PositiveFiniteFloat | None = None,
    ) -> Any:
        request = AssignMaterialRequest(
            analysis_id=analysis_id,
            document_id=document_id,
            material_id=material_id,
            name=name,
            youngs_modulus_pa=youngs_modulus_pa,
            poisson_ratio=poisson_ratio,
            density_kg_m3=density_kg_m3,
            yield_strength_pa=yield_strength_pa,
        )
        return await invoke("material", "assign", request)

    @app.tool(
        name="add_constraint",
        description=(
            "Add a bounded analysis constraint. Use targets with exact FreeCAD "
            "object_name and subelements, for example "
            "[{object_name: 'Cantilever', subelements: ['Face1']}]. "
            "Leave targets empty to use the current GUI selection; never use object_id."
        ),
        annotations=ann(readonly=False, destructive=False),
    )
    async def add_constraint(
        analysis_id: BoundedText,
        constraint_type: Literal["fixed", "displacement", "force", "pressure", "selfweight"],
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
        )
        return await invoke("constraint", "add", request)

    @app.tool(
        name="add_load",
        description=(
            "Add a typed SI load. Use force_n for force, pressure_pa for pressure, "
            "exactly three acceleration_m_s2 components for gravity or arbitrary "
            "acceleration, or rotation_frequency_hz plus one EdgeN axis reference "
            "for centrifugal load. Targets may be empty to use the current GUI "
            "selection (or all elements for centrifugal load)."
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
        )
        return await invoke("load", "add", request)

    @app.tool(
        name="add_remote_load",
        description=(
            "Add a remote global force and/or moment at a reference point. Targets "
            "must identify at least one coupled region; reference_point_m is in "
            "global meters, force_n in global newtons, and moment_n_m in global "
            "newton-meters. At least one load vector must be non-zero."
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
    ) -> Any:
        request = AddRemoteLoadRequest(
            analysis_id=analysis_id,
            targets=targets,
            reference_point_m=reference_point_m,
            document_id=document_id,
            force_n=force_n,
            moment_n_m=moment_n_m,
        )
        return await invoke("remote_load", "add", request)

    @app.tool(
        name="add_remote_displacement",
        description=(
            "Add a remote global displacement and/or rotation at a reference point. "
            "Targets must identify at least one coupled region; reference_point_m "
            "is in global meters, translation_m in global meters, and rotation_rad "
            "in global radians. Each numeric component constrains that DOF (including "
            "zero); null means Free. At least one component must be numeric."
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
    ) -> Any:
        request = AddRemoteDisplacementRequest(
            analysis_id=analysis_id,
            targets=targets,
            reference_point_m=reference_point_m,
            document_id=document_id,
            translation_m=translation_m,
            rotation_rad=rotation_rad,
        )
        return await invoke("remote_displacement", "add", request)

    @app.tool(
        name="add_boundary_condition",
        description=(
            "Add a fixed or prescribed-displacement boundary condition. Fixed "
            "conditions take no displacement; displacement requires exactly three "
            "displacement_m components in meters. Targets may be empty to use the "
            "current GUI selection."
        ),
        annotations=ann(readonly=False, destructive=False),
    )
    async def add_boundary_condition(
        analysis_id: BoundedText,
        boundary_type: Literal["fixed", "displacement"],
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
        displacement_m: Vector3 | None = None,
    ) -> Any:
        request = AddBoundaryConditionRequest(
            analysis_id=analysis_id,
            boundary_type=boundary_type,
            document_id=document_id,
            targets=targets or [],
            displacement_m=displacement_m,
        )
        return await invoke("boundary_condition", "add", request)

    @app.tool(
        name="create_mesh",
        description="Create a Gmsh analysis mesh.",
        annotations=ann(readonly=False, destructive=False),
    )
    async def create_mesh(
        analysis_id: BoundedText,
        document_id: BoundedText | None = None,
        element_size_mm: PositiveFiniteFloat | None = None,
        second_order: StrictBool = False,
        shape_id: BoundedText | None = None,
    ) -> Any:
        request = CreateMeshRequest(
            analysis_id=analysis_id,
            document_id=document_id,
            element_size_mm=element_size_mm,
            second_order=second_order,
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
        description="Read bounded solver results.",
        annotations=ann(readonly=True, destructive=False, idempotent=True),
    )
    async def get_results(
        analysis_id: BoundedText,
        field: Literal["displacement", "stress", "strain", "von_mises", "reaction"] | None = None,
        max_items: Annotated[StrictInt, Field(ge=1, le=10000)] = 1000,
    ) -> Any:
        request = GetResultsRequest(
            analysis_id=analysis_id,
            field=field,
            max_items=max_items,
        )
        return await invoke("results", "get", request)

    @app.tool(
        name="show_result",
        description="Show one bounded result field in FreeCAD.",
        annotations=ann(readonly=False, destructive=False, idempotent=True),
    )
    async def show_result(
        analysis_id: BoundedText,
        field: Literal["displacement", "stress", "strain", "von_mises", "reaction"] | None = None,
        max_items: Annotated[StrictInt, Field(ge=1, le=10000)] = 1000,
        frame: Annotated[StrictInt, Field(ge=0, le=100000)] = 0,
    ) -> Any:
        request = ShowResultRequest(
            analysis_id=analysis_id,
            field=field,
            max_items=max_items,
            frame=frame,
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
