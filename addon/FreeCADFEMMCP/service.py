"""Strict method/action router for the addon bridge."""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from .jobs import QProcessJobRegistry
from .operations import FreeCADOperations
from .pipeline import FemPostPipeline
from .protocol import Request
from .selection import SelectionCapture
from .version import host_version


class ServiceError(RuntimeError):
    pass


# R6 audit gates: these capabilities have no verified FreeCAD 1.1.3 native
# document object *and* CalculiX writer pair.  Keep the machine-readable list
# bounded and stable; listing a gate does not expose a route or an INP/legacy
# fallback.
_R6_FUTURE_GATES: tuple[str, ...] = (
    "load_case",
    "multi_step",
    "combination",
    "envelope",
    "bolt_pretension",
    "mechanical_initial_stress_strain",
    "concentrated_mass_rotational_inertia",
    "damper",
    "connector_release",
)


# Public requests are modelled as one fixed action per bridge method.  Keep
# this table next to the router so a direct Addon caller cannot smuggle an
# unused ``code``, ``inp``, or FreeCAD property through a valid action.
_ROUTE_CONTRACTS: dict[tuple[str, str], tuple[set[str], set[str]]] = {
    ("status", "get"): ({"action"}, {"action"}),
    ("document", "active"): ({"action", "document_id"}, {"action"}),
    ("selection", "get"): ({"action", "document_id"}, {"action"}),
    ("view", "set"): ({"action", "document_id", "orientation", "fit"}, {"action"}),
    ("capture", "capture"): (
        {"action", "document_id", "width", "height", "image_format", "scope"},
        {"action", "scope"},
    ),
    ("open", "open"): ({"action", "path"}, {"action", "path"}),
    ("save", "save"): (
        {"action", "document_id", "path", "overwrite", "expected_revision"},
        {"action"},
    ),
    ("analysis", "create"): (
        {
            "action", "document_id", "name", "solver", "analysis_type",
            "eigenmodes_count", "frequency_low_hz", "frequency_high_hz",
            "buckling_factors", "buckling_accuracy", "geometrical_nonlinearity",
            "material_nonlinearity", "automatic_incrementation",
            "time_initial_increment_s", "time_minimum_increment_s",
            "time_maximum_increment_s", "time_period_s", "increments_maximum",
        },
        {"action"},
    ),
    ("connection", "add"): (
        {
            "action", "document_id", "analysis_id", "connection_type",
            "slave", "master", "tolerance_m", "adjust", "surface_behavior",
            "friction", "friction_coefficient", "normal_stiffness_pa_per_m",
            "stick_stiffness_pa_per_m", "adjust_m", "sectors", "connected_sectors",
        },
        {"action", "analysis_id", "connection_type", "slave", "master"},
    ),
    ("material", "assign"): (
        {
            "action", "document_id", "analysis_id", "material_id", "name",
            "targets",
            "youngs_modulus_pa", "poisson_ratio", "density_kg_m3", "yield_strength_pa",
            "hardening_model", "yield_points",
        },
        {"action", "analysis_id"},
    ),
    ("mesh", "create"): (
        {"action", "document_id", "analysis_id", "element_size_mm", "second_order", "shape_id", "element_dimension"},
        {"action", "analysis_id"},
    ),
    ("element_geometry", "assign"): (
        {
            "action", "document_id", "analysis_id", "kind", "targets",
            "formulation", "thickness_m", "offset", "section_type", "rotation_rad",
            "rect_width_m", "rect_height_m", "circ_diameter_m",
            "pipe_diameter_m", "pipe_thickness_m", "axis1_length_m", "axis2_length_m",
            "box_width_m", "box_height_m", "box_t1_m", "box_t2_m", "box_t3_m", "box_t4_m",
            "truss_area_m2",
        },
        {"action", "analysis_id", "kind", "targets"},
    ),
    ("validate", "validate"): (
        {"action", "document_id", "analysis_id", "strict"},
        {"action", "analysis_id"},
    ),
    ("jobs", "start"): (
        {"action", "document_id", "analysis_id"},
        {"action", "analysis_id"},
    ),
    ("jobs", "get"): ({"action", "job_id"}, {"action", "job_id"}),
    ("jobs", "list"): ({"action", "analysis_id"}, {"action"}),
    ("jobs", "cancel"): ({"action", "job_id"}, {"action", "job_id"}),
    ("results", "get"): (
        {"action", "analysis_id", "field", "max_items", "mode", "frame"},
        {"action", "analysis_id"},
    ),
    ("results", "show"): (
        {"action", "analysis_id", "field", "max_items", "mode", "frame"},
        {"action", "analysis_id"},
    ),
}


class FEMService:
    """Map the finite public method/action surface to native operations.

    Action names deliberately match the dedicated core wrappers exactly; no
    aliases or dynamic method lookup are accepted.
    """

    def __init__(self, operations: Optional[FreeCADOperations] = None, selection: Optional[SelectionCapture] = None, jobs: Optional[QProcessJobRegistry] = None, pipeline: Optional[FemPostPipeline] = None):
        self.operations = operations or FreeCADOperations()
        self.selection = selection or SelectionCapture()
        self.jobs = jobs or QProcessJobRegistry()
        self.pipeline = pipeline or FemPostPipeline(getattr(self.operations, "app", None), getattr(self.selection, "gui", None))

    @staticmethod
    def _action(params: Mapping[str, Any], expected: str | set[str]) -> str:
        action = params.get("action")
        allowed = {expected} if isinstance(expected, str) else expected
        if not isinstance(action, str) or action not in allowed:
            raise ServiceError("unsupported action")
        return action

    def _object(self, object_id: Any) -> Any:
        if not isinstance(object_id, str) or not object_id:
            raise ServiceError("object id is required")
        return self.operations._find(self.operations._document(), object_id)

    def _analysis(self, analysis_id: Any) -> Any:
        return self._object(analysis_id)

    def _solver(self, analysis: Any) -> Any:
        for item in list(getattr(analysis, "Group", []) or []):
            if self.operations.fem_type(item) == "Fem::SolverCalculiX":
                return item
        raise ServiceError("analysis has no CalculiX solver")

    @staticmethod
    def _mesh(analysis: Any) -> Any:
        for item in list(getattr(analysis, "Group", []) or []):
            if "FemMesh" in getattr(item, "TypeId", ""):
                return item
        raise ServiceError("analysis has no mesh")

    def _validate_route_contract(self, method: str, params: Mapping[str, Any]) -> None:
        """Validate the closed public field set before dispatching an action.

        Pydantic protects the MCP process, but the local bridge is also a direct
        trust boundary.  This second check deliberately mirrors the public
        request models and selects a distinct field set for each job/results
        action.  The legacy ``constraint`` shape is handled by its compatibility
        validator below; typed load and boundary routes have stricter validators.
        """
        action = params.get("action")
        if method == "constraint":
            self._action(params, "add")
            self._validate_constraint_contract(params)
            return
        if method == "load":
            self._action(params, "add")
            self._validate_load_request(params)
            return
        if method == "boundary_condition":
            self._action(params, "add")
            self._validate_boundary_request(params)
            return
        if method == "remote_load":
            self._action(params, "add")
            self._validate_remote_load_request(params)
            return
        if method == "remote_displacement":
            self._action(params, "add")
            self._validate_remote_displacement_request(params)
            return
        if not isinstance(action, str):
            # The dispatch branch will emit the same safe unsupported-action
            # error.  Avoid attempting a dictionary lookup with an unhashable
            # attacker-controlled value here.
            return
        contract = _ROUTE_CONTRACTS.get((method, action))
        if contract is None:
            return
        allowed, required = contract
        self._validate_fields(params, allowed, required)
        self._validate_standard_fields(method, action, params)

    @staticmethod
    def _strict_bool(value: Any, name: str) -> bool:
        if not isinstance(value, bool):
            raise ServiceError("{} must be boolean".format(name))
        return value

    @staticmethod
    def _strict_int(value: Any, name: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ServiceError("{} is outside the allowed range".format(name))
        return value

    @classmethod
    def _optional_text(cls, params: Mapping[str, Any], key: str, maximum: int = 256) -> None:
        if key not in params or params[key] is None:
            return
        value = params[key]
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
            raise ServiceError("{} is invalid".format(key))

    @classmethod
    def _optional_finite(cls, params: Mapping[str, Any], key: str, *, positive: bool = False) -> None:
        if key not in params or params[key] is None:
            return
        value = cls._finite_value(params[key], key, strict_numeric=True)
        if positive and value <= 0.0:
            raise ServiceError("{} must be positive".format(key))

    @classmethod
    def _validate_standard_fields(cls, method: str, action: str, params: Mapping[str, Any]) -> None:
        if "document_id" in params:
            cls._require_identifier(params, "document_id")

        if method in {"document", "selection"}:
            return
        if method == "status":
            return
        if method == "view":
            cls._optional_text(params, "orientation", maximum=32)
            if "orientation" in params and params["orientation"] not in {
                "front", "rear", "left", "right", "top", "bottom", "isometric"
            }:
                raise ServiceError("orientation is unsupported")
            if "fit" in params:
                cls._strict_bool(params["fit"], "fit")
            return
        if method == "capture":
            cls._strict_int(params.get("width", 1280), "width", 16, 8192)
            cls._strict_int(params.get("height", 720), "height", 16, 8192)
            if params.get("image_format", "png") not in {"png", "jpeg"}:
                raise ServiceError("image_format is unsupported")
            if params.get("scope") not in {"viewport", "window"}:
                raise ServiceError("capture scope is required")
            return
        if method == "open":
            value = params.get("path")
            if not isinstance(value, str) or not value.strip() or len(value) > 512 or "\x00" in value:
                raise ServiceError("path is invalid")
            if any(ord(char) < 0x20 for char in value if char not in "\t"):
                raise ServiceError("path contains a control character")
            return
        if method == "save":
            cls._optional_text(params, "path", maximum=512)
            if "path" in params and params["path"] is not None:
                if any(ord(char) < 0x20 for char in params["path"] if char != "\t"):
                    raise ServiceError("path contains a control character")
            if "overwrite" in params:
                cls._strict_bool(params["overwrite"], "overwrite")
            if "expected_revision" in params and params["expected_revision"] is not None:
                revision = params["expected_revision"]
                if not isinstance(revision, str) or not revision.isdigit() or len(revision) > 256:
                    raise ServiceError("expected_revision is invalid")
            if params.get("overwrite", False) and not params.get("expected_revision"):
                raise ServiceError("expected_revision is required when overwrite=true")
            return
        if method == "analysis":
            cls._optional_text(params, "name")
            if params.get("solver", "SolverCalculiX") != "SolverCalculiX":
                raise ServiceError("solver is unsupported")
            cls._validate_analysis_options(params)
            return
        if method == "connection":
            cls._validate_connection_contract(params)
            return
        if method == "material":
            cls._require_identifier(params, "analysis_id")
            cls._optional_text(params, "material_id")
            cls._optional_text(params, "name")
            cls._validate_material_targets(params)
            cls._optional_finite(params, "youngs_modulus_pa", positive=True)
            cls._optional_finite(params, "poisson_ratio")
            if "poisson_ratio" in params and params["poisson_ratio"] is not None and not -1.0 < params["poisson_ratio"] < 0.5:
                raise ServiceError("poisson_ratio is outside the allowed range")
            cls._optional_finite(params, "density_kg_m3", positive=True)
            cls._optional_finite(params, "yield_strength_pa", positive=True)
            cls._validate_nonlinear_material(params)
            return
        if method == "element_geometry":
            cls._validate_element_geometry_request(params)
            return
        if method == "mesh":
            cls._require_identifier(params, "analysis_id")
            cls._optional_finite(params, "element_size_mm", positive=True)
            if "second_order" in params:
                cls._strict_bool(params["second_order"], "second_order")
            cls._optional_text(params, "shape_id")
            if "element_dimension" in params:
                dimension = params["element_dimension"]
                if dimension not in {"1d", "2d", "3d"}:
                    raise ServiceError("element_dimension is unsupported")
            return
        if method == "validate":
            cls._require_identifier(params, "analysis_id")
            if "strict" in params:
                cls._strict_bool(params["strict"], "strict")
            return
        if method == "jobs":
            if action in {"start"}:
                cls._require_identifier(params, "analysis_id")
            elif action in {"get", "cancel"}:
                cls._require_identifier(params, "job_id")
            elif action == "list" and "analysis_id" in params and params["analysis_id"] is not None:
                cls._require_identifier(params, "analysis_id")
            return
        if method == "results":
            cls._require_identifier(params, "analysis_id")
            if "field" in params and params["field"] is not None and params["field"] not in {
                "displacement", "stress", "strain", "von_mises", "reaction"
            }:
                raise ServiceError("result field is unsupported")
            if "max_items" in params:
                cls._strict_int(params["max_items"], "max_items", 1, 10000)
            if "mode" in params and params["mode"] is not None:
                cls._strict_int(params["mode"], "mode", 1, 100)
            if "frame" in params and params["frame"] is not None:
                cls._strict_int(params["frame"], "frame", 0, 100000)
            if params.get("mode") is not None and params.get("frame", 0) not in (None, 0):
                raise ServiceError("mode and nonzero frame cannot be combined")

    @classmethod
    def _validate_element_geometry_request(cls, params: Mapping[str, Any]) -> None:
        """Validate the closed native shell/beam geometry assignment route."""

        cls._require_identifier(params, "analysis_id")
        kind = params.get("kind")
        if kind not in {"shell", "beam_section", "beam_rotation"}:
            raise ServiceError("element geometry kind is unsupported")

        targets = params.get("targets")
        if not isinstance(targets, list) or not 1 <= len(targets) <= 128:
            raise ServiceError("element geometry targets must be a non-empty bounded list")
        seen: set[tuple[str, str]] = set()
        reference_count = 0
        prefix = "Face" if kind == "shell" else "Edge"
        for target in targets:
            if not isinstance(target, Mapping) or set(target) != {"object_name", "subelements"}:
                raise ServiceError("element geometry target must contain exactly object_name and subelements")
            object_name = target.get("object_name")
            if (
                not isinstance(object_name, str)
                or not object_name
                or len(object_name) > 256
                or "\x00" in object_name
                or any(ord(char) < 0x20 for char in object_name)
            ):
                raise ServiceError("element geometry target object_name is invalid")
            subelements = target.get("subelements")
            if not isinstance(subelements, list) or not 1 <= len(subelements) <= 64:
                raise ServiceError("element geometry target subelements are invalid")
            reference_count += len(subelements)
            if reference_count > 128:
                raise ServiceError("element geometry references are too numerous")
            for subelement in subelements:
                if not isinstance(subelement, str) or not subelement.startswith(prefix):
                    raise ServiceError("element geometry targets must use {}N".format(prefix))
                suffix = subelement[len(prefix):]
                if (
                    not suffix
                    or not suffix.isascii()
                    or not suffix.isdigit()
                    or int(suffix) <= 0
                    or (len(suffix) > 1 and suffix.startswith("0"))
                ):
                    raise ServiceError("element geometry targets must use {}N".format(prefix))
                key = (object_name, subelement)
                if key in seen:
                    raise ServiceError("element geometry targets must be unique")
                seen.add(key)

        common = {"action", "document_id", "analysis_id", "kind", "targets"}

        def bounded_number(key: str, *, minimum: float = 0.0, positive: bool = True) -> float:
            if key not in params or params[key] is None:
                raise ServiceError("{} is required".format(key))
            number = cls._finite_value(params[key], key, strict_numeric=True)
            if number > 1e6 or (positive and number <= minimum) or (not positive and number < minimum):
                raise ServiceError("{} is outside the allowed range".format(key))
            return number

        if kind == "shell":
            allowed = common | {"formulation", "thickness_m", "offset"}
            if set(params) - allowed:
                raise ServiceError("fields are not valid for shell geometry")
            if "formulation" in params and params["formulation"] not in {"shell", "membrane"}:
                raise ServiceError("formulation is unsupported")
            bounded_number("thickness_m")
            if "offset" in params:
                offset = cls._finite_value(params["offset"], "offset", strict_numeric=True)
                if not -1.0 <= offset <= 1.0:
                    raise ServiceError("offset is outside the allowed range")
            return

        if kind == "beam_rotation":
            allowed = common | {"rotation_rad"}
            if set(params) - allowed:
                raise ServiceError("fields are not valid for beam rotation geometry")
            bounded_number("rotation_rad", minimum=-1e6, positive=False)
            return

        section_fields = {
            "rectangular": {"rect_width_m", "rect_height_m"},
            "circular": {"circ_diameter_m"},
            "pipe": {"pipe_diameter_m", "pipe_thickness_m"},
            "elliptical": {"axis1_length_m", "axis2_length_m"},
            "box": {"box_width_m", "box_height_m", "box_t1_m", "box_t2_m", "box_t3_m", "box_t4_m"},
            "truss": {"truss_area_m2"},
        }
        section_type = params.get("section_type")
        if section_type not in section_fields:
            raise ServiceError("section_type is unsupported")
        allowed = common | {"section_type"} | section_fields[section_type]
        if set(params) - allowed:
            raise ServiceError("fields are not valid for beam section geometry")
        for field in section_fields[section_type]:
            bounded_number(field)
        if section_type == "pipe":
            if 2.0 * float(params["pipe_thickness_m"]) >= float(params["pipe_diameter_m"]):
                raise ServiceError("pipe thickness must be less than half the outer diameter")
        elif section_type == "box":
            if float(params["box_t1_m"]) + float(params["box_t3_m"]) >= float(params["box_height_m"]):
                raise ServiceError("box wall thicknesses must fit inside box dimensions")
            if float(params["box_t2_m"]) + float(params["box_t4_m"]) >= float(params["box_width_m"]):
                raise ServiceError("box wall thicknesses must fit inside box dimensions")

    @classmethod
    def _validate_material_targets(cls, params: Mapping[str, Any]) -> None:
        targets = params.get("targets")
        if targets is None:
            return
        if not isinstance(targets, list) or len(targets) > 128:
            raise ServiceError("material targets must be a bounded list")
        seen: set[tuple[str, str]] = set()
        for target in targets:
            if not isinstance(target, Mapping) or set(target) != {"object_name", "subelements"}:
                raise ServiceError("material target must contain exactly object_name and subelements")
            object_name = target.get("object_name")
            if (
                not isinstance(object_name, str)
                or not object_name.strip()
                or len(object_name) > 256
                or "\x00" in object_name
                or any(ord(char) < 0x20 for char in object_name)
            ):
                raise ServiceError("material target object_name is invalid")
            subelements = target.get("subelements")
            if not isinstance(subelements, list) or len(subelements) > 64:
                raise ServiceError("material target subelements are invalid")
            if not subelements:
                subelements = [""]
            for subelement in subelements:
                if not isinstance(subelement, str):
                    raise ServiceError("material targets must use VertexN, EdgeN, FaceN, or SolidN")
                if subelement:
                    prefix = next(
                        (candidate for candidate in ("Vertex", "Edge", "Face", "Solid") if subelement.startswith(candidate)),
                        None,
                    )
                    if prefix is None:
                        raise ServiceError("material targets must use VertexN, EdgeN, FaceN, or SolidN")
                    suffix = subelement[len(prefix):]
                    if (
                        not suffix
                        or not suffix.isascii()
                        or not suffix.isdigit()
                        or int(suffix) <= 0
                        or (len(suffix) > 1 and suffix.startswith("0"))
                    ):
                        raise ServiceError("material targets must use VertexN, EdgeN, FaceN, or SolidN")
                elif len(subelements) != 1:
                    raise ServiceError("whole-object material target cannot be combined with subelements")
                key = (object_name, subelement)
                if key in seen:
                    raise ServiceError("material targets must be unique")
                seen.add(key)
        for object_name, subelement in seen:
            if subelement == "" and any(
                other_object == object_name and other_subelement
                for other_object, other_subelement in seen
            ):
                raise ServiceError("whole-object material target cannot be combined with subelements")

    @classmethod
    def _validate_analysis_options(cls, params: Mapping[str, Any]) -> None:
        """Validate the mode-specific SolverCalculiX creation contract."""

        analysis_type = params.get("analysis_type", "static")
        if not isinstance(analysis_type, str) or analysis_type not in {"static", "frequency", "buckling"}:
            raise ServiceError("analysis_type is unsupported")

        eigenmodes_count = params.get("eigenmodes_count")
        frequency_low_hz = params.get("frequency_low_hz")
        frequency_high_hz = params.get("frequency_high_hz")
        buckling_factors = params.get("buckling_factors")
        buckling_accuracy = params.get("buckling_accuracy")
        geometrical_nonlinearity = params.get("geometrical_nonlinearity", "linear")
        material_nonlinearity = params.get("material_nonlinearity", "linear")
        automatic_incrementation = params.get("automatic_incrementation", True)
        time_names = (
            "time_initial_increment_s",
            "time_minimum_increment_s",
            "time_maximum_increment_s",
            "time_period_s",
        )
        time_values = {name: params.get(name) for name in time_names}
        increments_maximum = params.get("increments_maximum")
        if geometrical_nonlinearity not in {"linear", "nonlinear"}:
            raise ServiceError("geometrical_nonlinearity is unsupported")
        if material_nonlinearity not in {"linear", "nonlinear"}:
            raise ServiceError("material_nonlinearity is unsupported")
        cls._strict_bool(automatic_incrementation, "automatic_incrementation")
        if increments_maximum is not None:
            cls._strict_int(increments_maximum, "increments_maximum", 1, 1_000_000)
        supplied_time_values = [value for value in time_values.values() if value is not None]
        if supplied_time_values and len(supplied_time_values) != len(time_values):
            raise ServiceError("all time increment controls are required together")
        normalized_times: dict[str, float] = {}
        for name, value in time_values.items():
            if value is None:
                continue
            normalized_times[name] = cls._finite_value(value, name, strict_numeric=True)
            if not 1e-12 <= normalized_times[name] <= 1e9:
                raise ServiceError("{} is outside the allowed range".format(name))
        initial = normalized_times.get("time_initial_increment_s")
        minimum = normalized_times.get("time_minimum_increment_s")
        maximum = normalized_times.get("time_maximum_increment_s")
        period = normalized_times.get("time_period_s")
        if normalized_times:
            assert initial is not None and minimum is not None and maximum is not None and period is not None
            if minimum > initial or initial > maximum or maximum > period:
                raise ServiceError(
                    "time controls must satisfy minimum <= initial <= maximum <= period"
                )
        frequency_fields = (eigenmodes_count, frequency_low_hz, frequency_high_hz)
        buckling_fields = (buckling_factors, buckling_accuracy)

        if analysis_type == "static":
            if any(value is not None for value in (*frequency_fields, *buckling_fields)):
                raise ServiceError("static analysis does not accept analysis-specific fields")
            return

        if (
            geometrical_nonlinearity != "linear"
            or material_nonlinearity != "linear"
            or automatic_incrementation is not True
            or supplied_time_values
            or increments_maximum is not None
        ):
            raise ServiceError("nonlinear/time controls are supported only for static analysis")

        if analysis_type == "frequency":
            if eigenmodes_count is None:
                raise ServiceError("eigenmodes_count is required for frequency analysis")
            cls._strict_int(eigenmodes_count, "eigenmodes_count", 1, 100)
            if (frequency_low_hz is None) != (frequency_high_hz is None):
                raise ServiceError(
                    "frequency_low_hz and frequency_high_hz must be provided together"
                )
            if any(value is not None for value in buckling_fields):
                raise ServiceError("frequency analysis does not accept buckling fields")
            if frequency_low_hz is not None:
                low = cls._finite_value(
                    frequency_low_hz, "frequency_low_hz", strict_numeric=True
                )
                high = cls._finite_value(
                    frequency_high_hz, "frequency_high_hz", strict_numeric=True
                )
                if not 0.0 <= low <= 1e9:
                    raise ServiceError("frequency_low_hz is outside the allowed range")
                if not 0.0 <= high <= 1e9:
                    raise ServiceError("frequency_high_hz is outside the allowed range")
                if high <= low:
                    raise ServiceError(
                        "frequency_high_hz must be greater than frequency_low_hz"
                    )
            return

        # Buckling mode: both controls are required, and no frequency fields
        # may leak through this direct bridge route.
        if buckling_factors is None:
            raise ServiceError("buckling_factors is required for buckling analysis")
        if buckling_accuracy is None:
            raise ServiceError("buckling_accuracy is required for buckling analysis")
        cls._strict_int(buckling_factors, "buckling_factors", 1, 100)
        accuracy = cls._finite_value(
            buckling_accuracy, "buckling_accuracy", strict_numeric=True
        )
        if not 0.0 < accuracy <= 1.0:
            raise ServiceError("buckling_accuracy is outside the allowed range")
        if any(value is not None for value in frequency_fields):
            raise ServiceError("buckling analysis does not accept frequency fields")

    @classmethod
    def _validate_nonlinear_material(cls, params: Mapping[str, Any]) -> None:
        """Validate the closed material hardening/point contract twice."""

        hardening = params.get("hardening_model")
        points = params.get("yield_points")
        if (hardening is None) != (points is None):
            raise ServiceError("hardening_model and yield_points must be provided together")
        if hardening is None:
            return
        if hardening not in {
            "isotropic", "kinematic"
        }:
            raise ServiceError("hardening_model is unsupported")
        if not isinstance(points, list) or not 1 <= len(points) <= 64:
            raise ServiceError("yield_points must contain between 1 and 64 points")
        previous_stress = 0.0
        previous_strain = 0.0
        for index, point in enumerate(points):
            if not isinstance(point, Mapping) or set(point) != {"stress_pa", "plastic_strain"}:
                raise ServiceError("yield point must contain exactly stress_pa and plastic_strain")
            stress = cls._finite_value(point["stress_pa"], "yield point stress_pa", strict_numeric=True)
            strain = cls._finite_value(point["plastic_strain"], "yield point plastic_strain", strict_numeric=True)
            if not 0.0 < stress <= 1e15 or not 0.0 <= strain <= 1e3:
                raise ServiceError("yield point is outside the allowed range")
            if index == 0 and strain != 0.0:
                raise ServiceError("yield_points first plastic_strain must be exactly 0.0")
            if stress <= previous_stress:
                raise ServiceError("yield_points stress_pa values must be strictly increasing")
            if strain < previous_strain:
                raise ServiceError("yield_points plastic_strain values must be nondecreasing")
            previous_stress = stress
            previous_strain = strain

    @classmethod
    def _validate_connection_target(cls, value: Any, name: str) -> tuple[str, str]:
        """Validate one closed EntityRef containing exactly one FaceN."""

        if not isinstance(value, Mapping) or set(value) != {"object_name", "subelements"}:
            raise ServiceError("{} must contain exactly object_name and subelements".format(name))
        object_name = value.get("object_name")
        if (
            not isinstance(object_name, str)
            or not object_name.strip()
            or len(object_name) > 256
            or "\x00" in object_name
        ):
            raise ServiceError("{} object_name is invalid".format(name))
        subelements = value.get("subelements")
        if not isinstance(subelements, list) or len(subelements) != 1:
            raise ServiceError("{} must contain exactly one face".format(name))
        subelement = subelements[0]
        if not isinstance(subelement, str) or not subelement.startswith("Face"):
            raise ServiceError("{} must use FaceN".format(name))
        suffix = subelement[4:]
        if (
            not suffix
            or not suffix.isascii()
            or not suffix.isdigit()
            or int(suffix) <= 0
            or (len(suffix) > 1 and suffix.startswith("0"))
        ):
            raise ServiceError("{} must use FaceN".format(name))
        return object_name, subelement

    @classmethod
    def _validate_connection_contract(cls, params: Mapping[str, Any]) -> None:
        connection_type = params.get("connection_type")
        if not isinstance(connection_type, str) or connection_type not in {
            "tie", "contact", "cyclic_symmetry"
        }:
            raise ServiceError("connection_type is unsupported")
        slave_name, slave_face = cls._validate_connection_target(params.get("slave"), "slave")
        master_name, master_face = cls._validate_connection_target(params.get("master"), "master")
        if slave_name == master_name and slave_face == master_face:
            raise ServiceError("slave and master faces must be distinct")

        if connection_type in {"tie", "cyclic_symmetry"}:
            if "surface_behavior" in params:
                raise ServiceError("surface_behavior is unsupported for tie")
            if "friction" in params or any(
                field in params
                for field in (
                    "friction_coefficient",
                    "normal_stiffness_pa_per_m",
                    "stick_stiffness_pa_per_m",
                    "adjust_m",
                )
            ):
                raise ServiceError("contact fields are unsupported for tie")
            if "tolerance_m" not in params or params["tolerance_m"] is None:
                raise ServiceError("tolerance_m is required for tie")
            tolerance = cls._finite_value(
                params["tolerance_m"], "tolerance_m", strict_numeric=True
            )
            if not 0.0 <= tolerance <= 1e6:
                raise ServiceError("tolerance_m is outside the allowed range")
            if "adjust" not in params or params["adjust"] is None:
                raise ServiceError("adjust is required for tie")
            cls._strict_bool(params["adjust"], "adjust")
            if connection_type == "cyclic_symmetry":
                sectors = params.get("sectors")
                connected_sectors = params.get("connected_sectors")
                cls._strict_int(sectors, "sectors", 2, 1_000_000)
                cls._strict_int(connected_sectors, "connected_sectors", 1, 1_000_000)
                if connected_sectors >= sectors:
                    raise ServiceError("connected_sectors must be less than sectors")
            elif "sectors" in params or "connected_sectors" in params:
                raise ServiceError("cyclic symmetry fields are unsupported for tie")
            return

        # Native ConstraintContact controls are deliberately limited to the
        # CalculiX writer's solid face-to-face fields.  Thermal conductance,
        # shell/multi-face/autopair and arbitrary native properties remain out
        # of this bridge contract.
        surface_behavior = params.get("surface_behavior")
        if surface_behavior not in {"hard", "linear", "tied"}:
            raise ServiceError("surface_behavior is unsupported for contact")
        for forbidden in ("tolerance_m", "adjust"):
            if forbidden in params:
                raise ServiceError("{} is unsupported for contact".format(forbidden))
        for forbidden in ("sectors", "connected_sectors"):
            if forbidden in params:
                raise ServiceError("{} is unsupported for contact".format(forbidden))
        friction = params.get("friction", False)
        cls._strict_bool(friction, "friction")
        if surface_behavior in {"linear", "tied"}:
            if "normal_stiffness_pa_per_m" not in params:
                raise ServiceError(
                    "normal_stiffness_pa_per_m is required for linear/tied contact"
                )
            normal_stiffness = cls._finite_value(
                params["normal_stiffness_pa_per_m"],
                "normal_stiffness_pa_per_m",
                strict_numeric=True,
            )
            if not 0.0 < normal_stiffness <= 1e15:
                raise ServiceError("normal_stiffness_pa_per_m is outside the allowed range")
        elif "normal_stiffness_pa_per_m" in params:
            raise ServiceError(
                "normal_stiffness_pa_per_m is only valid for linear/tied contact"
            )
        if friction:
            if "friction_coefficient" not in params:
                raise ServiceError("friction_coefficient is required when friction is true")
            if "stick_stiffness_pa_per_m" not in params:
                raise ServiceError(
                    "stick_stiffness_pa_per_m is required when friction is true"
                )
            coefficient = cls._finite_value(
                params["friction_coefficient"],
                "friction_coefficient",
                strict_numeric=True,
            )
            if not 0.0 < coefficient <= 10.0:
                raise ServiceError("friction_coefficient is outside the allowed range")
            stick_stiffness = cls._finite_value(
                params["stick_stiffness_pa_per_m"],
                "stick_stiffness_pa_per_m",
                strict_numeric=True,
            )
            if not 0.0 < stick_stiffness <= 1e15:
                raise ServiceError(
                    "stick_stiffness_pa_per_m is outside the allowed range"
                )
        elif any(
            field in params
            for field in ("friction_coefficient", "stick_stiffness_pa_per_m")
        ):
            raise ServiceError(
                "friction_coefficient and stick_stiffness_pa_per_m require friction=true"
            )
        if "adjust_m" in params:
            adjust_m = cls._finite_value(params["adjust_m"], "adjust_m", strict_numeric=True)
            if not 0.0 <= adjust_m <= 1e6:
                raise ServiceError("adjust_m is outside the allowed range")

    @classmethod
    def _connection_data(cls, params: Mapping[str, Any]) -> dict[str, Any]:
        cls._validate_connection_contract(params)
        data: dict[str, Any] = {
            "references": [
                {
                    "object": params["slave"]["object_name"],
                    "sub_element": params["slave"]["subelements"][0],
                },
                {
                    "object": params["master"]["object_name"],
                    "sub_element": params["master"]["subelements"][0],
                },
            ]
        }
        if params["connection_type"] in {"tie", "cyclic_symmetry"}:
            if "tolerance_m" in params and params["tolerance_m"] is not None:
                data["tolerance_m"] = cls._finite_value(
                    params["tolerance_m"], "tolerance_m", strict_numeric=True
                )
            if "adjust" in params:
                data["adjust"] = params["adjust"]
            if params["connection_type"] == "cyclic_symmetry":
                data["sectors"] = params["sectors"]
                data["connected_sectors"] = params["connected_sectors"]
        else:
            data["surface_behavior"] = params["surface_behavior"]
            if "friction" in params:
                data["friction"] = params["friction"]
            for field in (
                "friction_coefficient",
                "normal_stiffness_pa_per_m",
                "stick_stiffness_pa_per_m",
                "adjust_m",
            ):
                if field in params and params[field] is not None:
                    data[field] = cls._finite_value(
                        params[field], field, strict_numeric=True
                    )
        return data

    def _validate_constraint_contract(self, params: Mapping[str, Any]) -> None:
        # Keep the documented legacy target aliases, but do not permit an
        # arbitrary native property/name/code field through this compatibility
        # method.  Typed routes use the narrower contracts above.
        allowed = {
            "action", "document_id", "analysis_id", "constraint_id", "constraint_type",
            "targets", "displacement_m", "force_n", "pressure_pa",
            "selfweight_acceleration_m_s2", "object_name", "subelements",
            "transform_type", "base_point_m", "axis_m", "rotation_rad",
        }
        self._validate_fields(params, allowed, {"action", "analysis_id", "constraint_type"})
        self._require_identifier(params, "analysis_id")
        if "document_id" in params:
            self._require_identifier(params, "document_id")
        if params["constraint_type"] not in {
            "fixed", "displacement", "force", "pressure", "selfweight", "plane_rotation", "transform"
        }:
            raise ServiceError("constraint_type is unsupported")
        if "constraint_id" in params and params["constraint_id"] is not None:
            self._optional_text(params, "constraint_id")
        if "targets" in params and not isinstance(params["targets"], list):
            raise ServiceError("targets must be a bounded list")
        if "object_name" in params:
            self._optional_text(params, "object_name")
        if "subelements" in params:
            if not isinstance(params["subelements"], list) or len(params["subelements"]) > 64:
                raise ServiceError("subelements are invalid")
            for subelement in params["subelements"]:
                if not isinstance(subelement, str) or not subelement or len(subelement) > 256:
                    raise ServiceError("subelements are invalid")
        for key in ("displacement_m", "force_n", "pressure_pa", "selfweight_acceleration_m_s2"):
            if key not in params:
                continue
            value = params[key]
            if isinstance(value, (list, tuple)):
                if len(value) > 32:
                    raise ServiceError("{} is too long".format(key))
                for component in value:
                    self._finite_value(component, key)
            else:
                self._finite_value(value, key)
        if params["constraint_type"] == "plane_rotation" and any(
            key in params and params[key] not in (None, [], ())
            for key in (
                "displacement_m",
                "force_n",
                "pressure_pa",
                "selfweight_acceleration_m_s2",
            )
        ):
            raise ServiceError("value fields are unsupported for plane_rotation")
        if params["constraint_type"] == "transform":
            targets = params.get("targets")
            if not isinstance(targets, list) or not targets:
                raise ServiceError("transform requires explicit targets")
            if params.get("transform_type") not in {"rectangular", "cylindrical"}:
                raise ServiceError("transform_type is unsupported")
            for key in ("base_point_m", "axis_m", "rotation_rad"):
                if key in params and params[key] is not None:
                    vector = self._finite_vector(params[key], key, strict_numeric=True)
                    if any(abs(component) > 1e9 for component in vector):
                        raise ServiceError("{} is outside the allowed range".format(key))
            transform_type = params["transform_type"]
            if transform_type == "rectangular":
                if "base_point_m" in params or params.get("rotation_rad") is None or "axis_m" in params:
                    raise ServiceError("rectangular transform requires rotation_rad only")
                if any(abs(component) > 1e6 for component in params["rotation_rad"]):
                    raise ServiceError("rotation_rad is outside the allowed range")
            else:
                if params.get("base_point_m") is None or params.get("axis_m") is None or params.get("rotation_rad") is not None:
                    raise ServiceError("cylindrical transform requires base_point_m and axis_m only")
                axis = self._finite_vector(params["axis_m"], "axis_m", strict_numeric=True)
                if math.sqrt(sum(component * component for component in axis)) <= 0.0:
                    raise ServiceError("axis_m must have a non-zero norm")
            if any(
                key in params and params[key] not in (None, [], ())
                for key in (
                    "displacement_m", "force_n", "pressure_pa", "selfweight_acceleration_m_s2",
                )
            ):
                raise ServiceError("value fields are unsupported for transform")
            self._validate_material_targets({"targets": targets})

    def __call__(self, request: Request) -> Any:
        params = request.params
        method = request.method
        if not isinstance(params, Mapping):
            raise ServiceError("params must be an object")
        self._validate_route_contract(method, params)
        document_id = params.get("document_id")
        if document_id is not None:
            if not isinstance(document_id, str) or not document_id:
                raise ServiceError("document_id is invalid")
            active = self.operations._document()
            active_name = getattr(active, "Name", "")
            if document_id != active_name:
                raise ServiceError("document_id does not identify the active document")

        if method == "status":
            self._action(params, "get")
            app = getattr(self.operations, "app", None)
            version = None
            if app is not None:
                version = ".".join(str(part) for part in host_version(app))
            return {
                "ready": True,
                "version": version,
                "capabilities": {
                    "analysis_types": ["static", "frequency", "buckling"],
                    "loads": [
                        "force", "pressure", "gravity", "acceleration", "centrifugal",
                        "remote_force", "remote_moment",
                    ],
                    "boundary_conditions": [
                        "fixed", "displacement", "pin", "roller", "remote_displacement",
                    ],
                    "connections": ["tie", "contact", "cyclic_symmetry"],
                    "mpc_types": ["plane_rotation"],
                    "result_kinds": ["displacement", "stress", "strain", "von_mises", "reaction"],
                    "element_dimensions": ["1d", "2d", "3d"],
                    "element_geometry": {
                        "shell": {
                            "references": "Face",
                            "formulations": ["shell", "membrane"],
                            "fields": ["formulation", "thickness_m", "offset"],
                        },
                        "beam_section": {
                            "references": "Edge",
                            "section_types": ["rectangular", "circular", "pipe", "elliptical", "box", "truss"],
                        },
                        "beam_rotation": {"references": "Edge", "fields": ["rotation_rad"]},
                    },
                    "material_assignment": {
                        "references": "Vertex|Edge|Face|Solid",
                        "multiple_regions": True,
                        "global_without_references": True,
                    },
                    "constraint_transform": {
                        "transform_types": ["rectangular", "cylindrical"],
                        "references": "Vertex|Edge|Face|Solid",
                        "rectangular_rotation": "axis-angle-radians",
                    },
                    "future_gates": list(_R6_FUTURE_GATES),
                },
            }

        if method == "document":
            self._action(params, "active")
            return self.operations.active_document()

        if method == "selection":
            self._action(params, "get")
            return self.selection.capture()

        if method == "view":
            self._action(params, "set")
            self._set_view(params)
            return {"set": True}

        if method == "capture":
            self._action(params, "capture")
            scope = params.get("scope")
            if scope not in {"viewport", "window"}:
                raise ServiceError("capture scope is required")
            return self.selection.capture_viewport(int(params.get("width", 1280)), int(params.get("height", 720)), scope, params.get("image_format", "png"))

        if method == "open":
            self._action(params, "open")
            return self.operations.open_document(params.get("path"))

        if method == "save":
            self._action(params, "save")
            overwrite = bool(params.get("overwrite", False))
            if overwrite:
                expected = params.get("expected_revision")
                if not isinstance(expected, str) or not expected.isdigit():
                    raise ServiceError("expected_revision is required when overwrite=true")
                if int(expected) != self.operations.revision():
                    raise ServiceError("document revision conflict")
            return self.operations.save_document(params.get("path"), overwrite)

        if method == "analysis":
            self._action(params, "create")
            analysis_type = params.get("analysis_type", "static")
            # Preserve the established frequency/buckling wire contract: R3
            # controls are forwarded only for static analyses and only when a
            # caller explicitly supplied the field.  The operation layer owns
            # its native linear/time defaults when these kwargs are absent.
            analysis_kwargs: dict[str, Any] = {
                "analysis_type": analysis_type,
                "eigenmodes_count": params.get("eigenmodes_count"),
                "frequency_low_hz": params.get("frequency_low_hz"),
                "frequency_high_hz": params.get("frequency_high_hz"),
                "buckling_factors": params.get("buckling_factors"),
                "buckling_accuracy": params.get("buckling_accuracy"),
            }
            if analysis_type == "static":
                r3_defaults: dict[str, Any] = {
                    "geometrical_nonlinearity": params.get("geometrical_nonlinearity"),
                    "material_nonlinearity": params.get("material_nonlinearity"),
                    "automatic_incrementation": params.get("automatic_incrementation"),
                    "time_initial_increment_s": params.get("time_initial_increment_s"),
                    "time_minimum_increment_s": params.get("time_minimum_increment_s"),
                    "time_maximum_increment_s": params.get("time_maximum_increment_s"),
                    "time_period_s": params.get("time_period_s"),
                    "increments_maximum": params.get("increments_maximum"),
                }
                analysis_kwargs.update(
                    {key: value for key, value in r3_defaults.items() if key in params}
                )
            result = self.operations.create_analysis(
                params.get("name", "Analysis"),
                **analysis_kwargs,
            )
            return {"analysis_id": result["name"], **result}

        if method == "material":
            self._action(params, "assign")
            material_fields = {
                "name", "targets", "youngs_modulus_pa", "poisson_ratio", "density_kg_m3",
                "yield_strength_pa", "hardening_model", "yield_points",
            }
            material = {
                key: params[key]
                for key in material_fields
                if key in params
            }
            # ``material_id`` is the established route-level name alias; it
            # never crosses into operations as an unsupported control field.
            if "name" not in material and params.get("material_id") is not None:
                material["name"] = params["material_id"]
            result = self.operations.set_material(params.get("analysis_id"), material)
            return {"material_id": result["name"], **result}

        if method == "constraint":
            self._action(params, "add")
            kind = params.get("constraint_type")
            constraint = self._constraint_data(params, kind, strict=False)
            result = self.operations.add_constraint(params.get("analysis_id"), kind, constraint)
            return {"constraint_id": result["name"], **result}

        if method == "load":
            self._action(params, "add")
            load_type = self._validate_load_request(params)
            kind = {
                "force": "force", "pressure": "pressure", "gravity": "selfweight",
                "acceleration": "selfweight", "centrifugal": "centrifugal",
            }[load_type]
            load = self._constraint_data(params, kind, strict=True)
            if kind == "centrifugal":
                result = self.operations.add_centrifugal_load(params["analysis_id"], load)
            else:
                result = self.operations.add_constraint(params["analysis_id"], kind, load)
            return {"load_id": result["name"], **result}

        if method == "boundary_condition":
            self._action(params, "add")
            boundary_type = self._validate_boundary_request(params)
            boundary = self._constraint_data(params, boundary_type, strict=True)
            result = self.operations.add_constraint(params["analysis_id"], boundary_type, boundary)
            return {"boundary_condition_id": result["name"], **result}

        if method == "remote_load":
            self._action(params, "add")
            remote = self._validate_remote_load_request(params)
            result = self.operations.add_remote_load(params["analysis_id"], remote)
            return {"remote_load_id": result["name"], **result}

        if method == "remote_displacement":
            self._action(params, "add")
            remote = self._validate_remote_displacement_request(params)
            result = self.operations.add_remote_displacement(params["analysis_id"], remote)
            return {"remote_displacement_id": result["name"], **result}

        if method == "connection":
            self._action(params, "add")
            connection = self._connection_data(params)
            result = self.operations.add_connection(
                params["analysis_id"], params["connection_type"], connection
            )
            return {"connection_id": result["name"], **result}

        if method == "element_geometry":
            self._action(params, "assign")
            # Typed geometry assignment never falls back to GUI selection:
            # references are explicit FaceN/EdgeN EntityRefs and are passed in
            # the native operation spelling only after strict validation.
            geometry = {
                key: value
                for key, value in params.items()
                if key not in {"action", "document_id", "analysis_id", "kind", "targets"}
            }
            geometry["references"] = self._references(params["targets"], strict_targets=True)
            result = self.operations.assign_element_geometry(
                params["analysis_id"], params["kind"], geometry
            )
            return {"element_geometry_id": result["name"], **result}

        if method == "mesh":
            self._action(params, "create")
            settings = dict(params)
            settings.pop("action", None)
            settings.pop("analysis_id", None)
            element_size = params.get("element_size_mm")
            if element_size is not None:
                settings["CharacteristicLengthMax"] = element_size
                settings["CharacteristicLengthMin"] = element_size
            if "second_order" in params:
                settings["ElementOrder"] = 2 if params["second_order"] else 1
            settings.setdefault("shape", params.get("shape_id"))
            if settings.get("shape") is None:
                captured = self.selection.capture()
                if captured["items"]:
                    settings["shape"] = captured["items"][0]["object"]
            result = self.operations.create_mesh(params.get("analysis_id"), params.get("name", "GmshMesh"), **settings)
            mesh_job = self.jobs.start_gmsh(self._object(result["name"]))
            return {"mesh_id": result["name"], "job": mesh_job, **result}

        if method == "validate":
            self._action(params, "validate")
            return self.operations.validate(
                params.get("analysis_id"), strict=params.get("strict", True)
            )

        if method == "jobs":
            action = self._action(params, {"start", "get", "list", "cancel"})
            if action == "start":
                analysis = self._analysis(params.get("analysis_id"))
                mesh = self._mesh(analysis)
                mesh_job = self.jobs.find_for_object(mesh, "gmsh")
                if mesh_job is None or mesh_job.get("state") != "completed":
                    raise ServiceError("Gmsh mesh job has not completed")
                fem_mesh = getattr(mesh, "FemMesh", None)
                if fem_mesh is None:
                    raise ServiceError("Gmsh produced no native mesh")
                counts = []
                for count_name in ("CountNodes", "CountEdges", "CountFaces", "CountVolumes"):
                    count_value = getattr(fem_mesh, count_name, None)
                    if callable(count_value):
                        try:
                            counts.append(int(count_value()))
                        except Exception:
                            pass
                if counts and max(counts) <= 0:
                    raise ServiceError("Gmsh produced an empty mesh")
                validation = self.operations.validate(getattr(analysis, "Name", ""))
                if not validation["valid"]:
                    raise ServiceError("analysis validation failed")
                return self.jobs.start_calculix(self._solver(analysis))
            if action == "get":
                return self.jobs.get(params.get("job_id"))
            if action == "list":
                jobs = self.jobs.list()
                if params.get("analysis_id"):
                    analysis = self._analysis(params.get("analysis_id"))
                    related_ids = set()
                    for native in (self._mesh(analysis), self._solver(analysis)):
                        related = self.jobs.find_for_object(native)
                        if related is not None:
                            related_ids.add(related["id"])
                    jobs = [job for job in jobs if job.get("id") in related_ids]
                return jobs
            return self.jobs.cancel(params.get("job_id"))

        if method == "results":
            action = self._action(params, {"get", "show"})
            analysis_type = None
            if params.get("analysis_id"):
                solver = self._solver(self._analysis(params.get("analysis_id")))
                analysis_type = getattr(solver, "AnalysisType", None)
            elif params.get("job_id"):
                solver = self.jobs.native_object(params.get("job_id"))
                analysis_type = getattr(solver, "AnalysisType", None)
            else:
                raise ServiceError("analysis_id or job_id is required")
            results = getattr(solver, "Results", None)
            if results is None:
                raise ServiceError("solver has no imported results")
            limit = int(params.get("max_items", 8192))
            mode = params.get("mode")
            raw_frame = params.get("frame", 0)
            frame = 0 if raw_frame is None else int(raw_frame)
            if action == "get":
                summary = self.pipeline.query_native(
                    results,
                    params.get("field"),
                    frame,
                    limit,
                    mode=mode,
                    analysis_type=analysis_type,
                )
                related = self.jobs.find_for_object(solver, "calculix")
                if isinstance(related, Mapping) and related.get("convergence") is not None:
                    summary["convergence"] = related["convergence"]
                return summary
            summary = self.pipeline.show_native(
                results, params.get("field"), frame, limit, mode=mode,
                analysis_type=analysis_type,
            )
            related = self.jobs.find_for_object(solver, "calculix")
            if isinstance(related, Mapping) and related.get("convergence") is not None:
                summary["convergence"] = related["convergence"]
            return summary

        raise ServiceError("method is not implemented")

    def _references(self, targets: Any, *, strict_targets: bool = False) -> list[dict[str, str]]:
        if not targets:
            captured = self.selection.capture()
            references: list[dict[str, str]] = []
            for item in captured["items"]:
                subelements = item.get("sub_elements", [])
                if not subelements:
                    # FreeCAD's object-only GUI selection has no
                    # ``SubElementNames``.  Preserve it as the same explicit
                    # whole-shape sentinel used by EntityRef.subelements=[];
                    # otherwise the native operation receives an empty list
                    # and rejects the boundary.
                    references.append({"object": item["object"], "sub_element": ""})
                    continue
                references.extend(
                    {"object": item["object"], "sub_element": sub}
                    for sub in subelements
                )
            return references
        if not isinstance(targets, list) or len(targets) > 128:
            raise ServiceError("targets must be a bounded list")
        references = []
        for target in targets:
            if not isinstance(target, Mapping) or not isinstance(target.get("object_name"), str):
                raise ServiceError("target is invalid")
            if strict_targets and set(target) != {"object_name", "subelements"}:
                raise ServiceError("target has unknown fields")
            if not target.get("object_name") or len(target["object_name"]) > 256:
                raise ServiceError("target object_name is invalid")
            subelements = target.get("subelements", [])
            if not isinstance(subelements, list) or len(subelements) > 64:
                raise ServiceError("target subelements are invalid")
            # An explicitly named object with [] means its whole native Shape;
            # an omitted/empty targets list still means the current GUI
            # selection (handled above).  Keep the distinction in the native
            # reference sentinel instead of silently dropping the target.
            if not subelements:
                references.append({"object": target["object_name"], "sub_element": ""})
                continue
            for subelement in subelements:
                if not isinstance(subelement, str) or not subelement or len(subelement) > 256:
                    raise ServiceError("target subelement is invalid")
                references.append({"object": target["object_name"], "sub_element": subelement})
        return references

    @staticmethod
    def _finite_value(value: Any, name: str, *, strict_numeric: bool = False) -> float:
        """Return a finite SI number, rejecting booleans and non-numbers.

        The compatibility ``constraint`` route historically accepted values
        that FreeCAD could coerce (for example a one-item list or a numeric
        string).  New typed routes use ``strict_numeric=True`` so malformed
        JSON values cannot cross the addon boundary.
        """
        if isinstance(value, bool):
            raise ServiceError("{} must be numeric".format(name))
        if strict_numeric and not isinstance(value, (int, float)):
            raise ServiceError("{} must be numeric".format(name))
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ServiceError("{} must be numeric".format(name)) from exc
        if not math.isfinite(number):
            raise ServiceError("{} must be finite".format(name))
        return number

    @classmethod
    def _finite_vector(cls, value: Any, name: str, *, strict_numeric: bool = False) -> list[float]:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ServiceError("{} must contain exactly three components".format(name))
        return [
            cls._finite_value(component, "{} component".format(name), strict_numeric=strict_numeric)
            for component in value
        ]

    @classmethod
    def _finite_optional_vector(
        cls, value: Any, name: str, limit: float
    ) -> list[Optional[float]]:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ServiceError("{} must contain exactly three components".format(name))
        result: list[Optional[float]] = []
        for component in value:
            if component is None:
                result.append(None)
                continue
            number = cls._finite_value(
                component, "{} component".format(name), strict_numeric=True
            )
            if abs(number) > limit:
                raise ServiceError("{} is outside the allowed range".format(name))
            result.append(number)
        return result

    @classmethod
    def _validate_amplitude(cls, value: Any) -> Optional[list[dict[str, float]]]:
        """Validate a bounded, strict CalculiX amplitude sequence.

        The local addon bridge is a trust boundary in addition to the MCP
        request models.  Keep the wire shape closed and normalize all values
        to finite floats before forwarding them to native operations.
        """

        if value is None:
            return None
        if not isinstance(value, list) or not 2 <= len(value) <= 256:
            raise ServiceError("amplitude must contain between 2 and 256 points")

        points: list[dict[str, float]] = []
        previous_time: Optional[float] = None
        for index, point in enumerate(value):
            if not isinstance(point, Mapping) or set(point) != {"time_s", "scale"}:
                raise ServiceError("amplitude point must contain exactly time_s and scale")
            time_s = cls._finite_value(point["time_s"], "amplitude time_s", strict_numeric=True)
            scale = cls._finite_value(point["scale"], "amplitude scale", strict_numeric=True)
            if not 0.0 <= time_s <= 1e12:
                raise ServiceError("amplitude time_s is outside the allowed range")
            if abs(scale) > 1e9:
                raise ServiceError("amplitude scale is outside the allowed range")
            if index == 0 and time_s != 0.0:
                raise ServiceError("amplitude first time_s must be exactly 0.0")
            if previous_time is not None and time_s <= previous_time:
                raise ServiceError("amplitude time_s values must be strictly increasing")
            points.append({"time_s": time_s, "scale": scale})
            previous_time = time_s
        return points

    @classmethod
    def _compat_scalar(cls, value: Any, name: str) -> float:
        if isinstance(value, (list, tuple)):
            if not value:
                raise ServiceError("{} is required".format(name))
            value = value[0]
        return cls._finite_value(value, name)

    @classmethod
    def _compat_targets(cls, params: Mapping[str, Any]) -> Any:
        targets = params.get("targets", [])
        if not targets and params.get("object_name"):
            targets = [{"object_name": params["object_name"], "subelements": params.get("subelements", [])}]
        return targets

    @staticmethod
    def _require_identifier(params: Mapping[str, Any], key: str) -> str:
        value = params.get(key)
        if not isinstance(value, str) or not value or len(value) > 256 or "\x00" in value:
            raise ServiceError("{} is required".format(key))
        return value

    @classmethod
    def _validate_fields(cls, params: Mapping[str, Any], allowed: set[str], required: set[str]) -> None:
        unknown = set(params) - allowed
        if unknown:
            raise ServiceError("unknown fields: {}".format(", ".join(sorted(str(item) for item in unknown))))
        missing = required - set(params)
        if missing:
            raise ServiceError("missing fields: {}".format(", ".join(sorted(missing))))

    def _validate_load_request(self, params: Mapping[str, Any]) -> str:
        load_type = params.get("load_type")
        if load_type not in {"force", "pressure", "gravity", "acceleration", "centrifugal"}:
            raise ServiceError("load_type is unsupported")
        value_key = {
            "force": "force_n",
            "pressure": "pressure_pa",
            "gravity": "acceleration_m_s2",
            "acceleration": "acceleration_m_s2",
            "centrifugal": "rotation_frequency_hz",
        }[load_type]
        allowed = {"action", "document_id", "analysis_id", "targets", "load_type", value_key}
        if load_type in {"force", "pressure"}:
            allowed.add("amplitude")
        if load_type == "centrifugal":
            allowed.update({"axis", "force_n", "pressure_pa", "acceleration_m_s2"})
        self._validate_fields(params, allowed, {"action", "analysis_id", "load_type", value_key})
        self._require_identifier(params, "analysis_id")
        if "document_id" in params:
            self._require_identifier(params, "document_id")
        if "targets" in params and not isinstance(params["targets"], list):
            raise ServiceError("targets must be a bounded list")
        if load_type in {"gravity", "acceleration"}:
            acceleration = self._finite_vector(params[value_key], value_key, strict_numeric=True)
            if math.sqrt(sum(component * component for component in acceleration)) <= 0.0:
                raise ServiceError("{} must have a non-zero norm".format(value_key))
        elif load_type == "centrifugal":
            self._optional_finite(params, value_key, positive=True)
            self._require_centrifugal_request(params)
        else:
            value = params[value_key]
            if isinstance(value, (list, tuple)) or isinstance(value, bool):
                raise ServiceError("{} must be a finite scalar".format(value_key))
            self._finite_value(value, value_key, strict_numeric=True)
        if "amplitude" in params:
            self._validate_amplitude(params["amplitude"])
        return load_type

    def _require_centrifugal_request(self, params: Mapping[str, Any]) -> None:
        frequency = self._finite_value(
            params["rotation_frequency_hz"], "rotation_frequency_hz", strict_numeric=True
        )
        if frequency <= 0.0 or frequency > 1e9:
            raise ServiceError("rotation_frequency_hz is outside the allowed range")
        for forbidden in ("force_n", "pressure_pa", "acceleration_m_s2"):
            if forbidden in params and params[forbidden] is not None:
                raise ServiceError("{} is not valid for centrifugal load".format(forbidden))

        axis = params.get("axis")
        if not isinstance(axis, Mapping) or set(axis) != {"object_name", "subelements"}:
            raise ServiceError("axis must contain exactly object_name and subelements")
        object_name = axis.get("object_name")
        if (
            not isinstance(object_name, str)
            or not object_name.strip()
            or len(object_name) > 256
            or "\x00" in object_name
        ):
            raise ServiceError("axis object_name is invalid")
        subelements = axis.get("subelements")
        if not isinstance(subelements, list) or len(subelements) != 1:
            raise ServiceError("axis must contain exactly one subelement")
        subelement = subelements[0]
        if (
            not isinstance(subelement, str)
            or not subelement
            or len(subelement) > 256
            or not subelement.startswith("Edge")
            or not subelement[4:].isascii()
            or not subelement[4:].isdigit()
            or int(subelement[4:]) <= 0
        ):
            raise ServiceError("axis subelement must be EdgeN")

        targets = params.get("targets", [])
        if not isinstance(targets, list) or len(targets) > 128:
            raise ServiceError("targets must be a bounded list")
        for target in targets:
            if not isinstance(target, Mapping) or set(target) != {"object_name", "subelements"}:
                raise ServiceError("target must contain exactly object_name and subelements")
            target_name = target.get("object_name")
            if (
                not isinstance(target_name, str)
                or not target_name.strip()
                or len(target_name) > 256
                or "\x00" in target_name
            ):
                raise ServiceError("target object_name is invalid")
            target_subelements = target.get("subelements")
            if (
                not isinstance(target_subelements, list)
                or not target_subelements
                or len(target_subelements) > 64
            ):
                raise ServiceError("target subelements must be a non-empty bounded list")
            for target_subelement in target_subelements:
                if (
                    not isinstance(target_subelement, str)
                    or not target_subelement.startswith("Solid")
                    or not target_subelement[5:].isascii()
                    or not target_subelement[5:].isdigit()
                    or int(target_subelement[5:]) <= 0
                    or len(target_subelement) > 256
                ):
                    raise ServiceError("centrifugal targets must use SolidN")

    def _validate_boundary_request(self, params: Mapping[str, Any]) -> str:
        boundary_type = params.get("boundary_type")
        supported = {"fixed", "displacement", "pin", "roller"}
        if boundary_type not in supported:
            raise ServiceError("boundary_type is unsupported")
        allowed = {
            "action", "document_id", "analysis_id", "targets", "boundary_type",
            "axis", "normal_m", "displacement_m", "rotation_rad", "amplitude",
        }
        required = {"action", "analysis_id", "boundary_type"}
        if boundary_type == "displacement":
            if "axis" in params or "normal_m" in params:
                raise ServiceError("axis/normal_m are unsupported for displacement")
        elif boundary_type == "roller":
            if any(key in params for key in ("displacement_m", "rotation_rad", "amplitude")):
                raise ServiceError("displacement_m/rotation_rad/amplitude are unsupported for roller")
            has_axis = "axis" in params
            has_normal = "normal_m" in params
            if has_axis == has_normal:
                raise ServiceError("roller requires exactly one of axis or normal_m")
            if has_axis and params.get("axis") not in {"x", "y", "z"}:
                raise ServiceError("axis must be x, y, or z")
            if has_normal:
                normal = self._finite_vector(params["normal_m"], "normal_m", strict_numeric=True)
                nonzero = [abs(component) for component in normal if component != 0.0]
                if len(nonzero) != 1 or nonzero[0] != 1.0:
                    raise ServiceError("normal_m must be an axis-aligned unit vector")
        elif "axis" in params or "normal_m" in params:
            raise ServiceError("axis/normal_m are unsupported for this boundary type")
        self._validate_fields(params, allowed, required)
        self._require_identifier(params, "analysis_id")
        if "document_id" in params:
            self._require_identifier(params, "document_id")
        if "targets" in params and not isinstance(params["targets"], list):
            raise ServiceError("targets must be a bounded list")
        if boundary_type == "displacement":
            constrained = False
            if "displacement_m" in params and params["displacement_m"] is not None:
                vector = self._finite_optional_vector(params["displacement_m"], "displacement_m", 1e9)
                constrained = constrained or any(component is not None for component in vector)
            if "rotation_rad" in params and params["rotation_rad"] is not None:
                vector = self._finite_optional_vector(params["rotation_rad"], "rotation_rad", 1e6)
                constrained = constrained or any(component is not None for component in vector)
            if not constrained:
                raise ServiceError("displacement_m or rotation_rad must constrain a component")
            if "amplitude" in params:
                self._validate_amplitude(params["amplitude"])
        elif boundary_type != "roller":
            if "displacement_m" in params or "rotation_rad" in params or "amplitude" in params:
                raise ServiceError("displacement_m/rotation_rad/amplitude are unsupported for this boundary type")
        return boundary_type

    def _validate_remote_load_request(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Validate the strict global remote-force/moment request shape."""

        allowed = {
            "action", "document_id", "analysis_id", "targets", "reference_point_m",
            "force_n", "moment_n_m", "amplitude",
        }
        self._validate_fields(
            params,
            allowed,
            {"action", "analysis_id", "targets", "reference_point_m"},
        )
        self._require_identifier(params, "analysis_id")
        if "document_id" in params and params["document_id"] is not None:
            self._require_identifier(params, "document_id")

        targets = params.get("targets")
        if not isinstance(targets, list) or not targets or len(targets) > 128:
            raise ServiceError("targets must be a non-empty bounded list")
        shape_kind: Optional[str] = None
        for target in targets:
            if not isinstance(target, Mapping) or set(target) != {"object_name", "subelements"}:
                raise ServiceError("target must contain exactly object_name and subelements")
            object_name = target.get("object_name")
            if (
                not isinstance(object_name, str)
                or not object_name.strip()
                or len(object_name) > 256
                or "\x00" in object_name
            ):
                raise ServiceError("target object_name is invalid")
            subelements = target.get("subelements")
            if not isinstance(subelements, list) or not subelements or len(subelements) > 64:
                raise ServiceError("target subelements must be a non-empty bounded list")
            for subelement in subelements:
                if not isinstance(subelement, str) or not subelement or len(subelement) > 256:
                    raise ServiceError("target subelement is invalid")
                subelement_kind = next(
                    (
                        prefix
                        for prefix in ("Vertex", "Edge", "Face")
                        if (
                            subelement.startswith(prefix)
                            and subelement[len(prefix):].isascii()
                            and subelement[len(prefix):].isdigit()
                            and int(subelement[len(prefix):]) > 0
                        )
                    ),
                    None,
                )
                if subelement_kind is None:
                    raise ServiceError("target subelement must be Vertex, Edge, or Face")
                if shape_kind is None:
                    shape_kind = subelement_kind
                elif shape_kind != subelement_kind:
                    raise ServiceError("remote load targets must use one shape type")

        reference_point = self._finite_vector(
            params["reference_point_m"], "reference_point_m", strict_numeric=True
        )
        if any(abs(component) > 1e9 for component in reference_point):
            raise ServiceError("reference_point_m is outside the allowed range")

        data: dict[str, Any] = {
            "references": self._references(targets, strict_targets=True),
            "reference_point_m": reference_point,
        }
        nonzero = False
        for key in ("force_n", "moment_n_m"):
            if key not in params or params[key] is None:
                continue
            vector = self._finite_vector(params[key], key, strict_numeric=True)
            if any(abs(component) > 1e15 for component in vector):
                raise ServiceError("{} is outside the allowed range".format(key))
            data[key] = vector
            nonzero = nonzero or any(component != 0.0 for component in vector)
        if not nonzero:
            raise ServiceError("force_n or moment_n_m must contain a non-zero component")
        if "amplitude" in params:
            amplitude = self._validate_amplitude(params["amplitude"])
            if amplitude is not None:
                data["amplitude"] = amplitude
        return data

    def _validate_remote_displacement_request(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Validate a rigid-body kinematic reference-point request."""

        allowed = {
            "action", "document_id", "analysis_id", "targets", "reference_point_m",
            "translation_m", "rotation_rad", "amplitude",
        }
        self._validate_fields(
            params,
            allowed,
            {"action", "analysis_id", "targets", "reference_point_m"},
        )
        self._require_identifier(params, "analysis_id")
        if "document_id" in params and params["document_id"] is not None:
            self._require_identifier(params, "document_id")

        targets = params.get("targets")
        if not isinstance(targets, list) or not targets or len(targets) > 128:
            raise ServiceError("targets must be a non-empty bounded list")
        shape_kind: Optional[str] = None
        for target in targets:
            if not isinstance(target, Mapping) or set(target) != {"object_name", "subelements"}:
                raise ServiceError("target must contain exactly object_name and subelements")
            object_name = target.get("object_name")
            if (
                not isinstance(object_name, str)
                or not object_name.strip()
                or len(object_name) > 256
                or "\x00" in object_name
            ):
                raise ServiceError("target object_name is invalid")
            subelements = target.get("subelements")
            if not isinstance(subelements, list) or not subelements or len(subelements) > 64:
                raise ServiceError("target subelements must be a non-empty bounded list")
            for subelement in subelements:
                if not isinstance(subelement, str) or not subelement or len(subelement) > 256:
                    raise ServiceError("target subelement is invalid")
                subelement_kind = next(
                    (
                        prefix
                        for prefix in ("Vertex", "Edge", "Face")
                        if (
                            subelement.startswith(prefix)
                            and subelement[len(prefix):].isascii()
                            and subelement[len(prefix):].isdigit()
                            and int(subelement[len(prefix):]) > 0
                        )
                    ),
                    None,
                )
                if subelement_kind is None:
                    raise ServiceError("target subelement must be Vertex, Edge, or Face")
                if shape_kind is None:
                    shape_kind = subelement_kind
                elif shape_kind != subelement_kind:
                    raise ServiceError("remote displacement targets must use one shape type")

        reference_point = self._finite_vector(
            params["reference_point_m"], "reference_point_m", strict_numeric=True
        )
        if any(abs(component) > 1e9 for component in reference_point):
            raise ServiceError("reference_point_m is outside the allowed range")

        data: dict[str, Any] = {
            "references": self._references(targets, strict_targets=True),
            "reference_point_m": reference_point,
        }
        constrained = False
        for key, limit in (("translation_m", 1e9), ("rotation_rad", 1e6)):
            if key not in params or params[key] is None:
                continue
            vector = self._finite_optional_vector(params[key], key, limit)
            if any(component is not None for component in vector):
                constrained = True
            data[key] = vector
        if not constrained:
            raise ServiceError("translation_m or rotation_rad must constrain a component")
        if "amplitude" in params:
            amplitude = self._validate_amplitude(params["amplitude"])
            if amplitude is not None:
                data["amplitude"] = amplitude
        return data

    def _constraint_data(self, params: Mapping[str, Any], kind: Any, *, strict: bool) -> dict[str, Any]:
        """Build native constraint data for both the compatibility and typed routes.

        Target resolution and conversion to native SI fields intentionally live
        here so ``constraint``, ``load`` and ``boundary_condition`` cannot drift
        in their handling of GUI selection, references, or vectors.
        """
        if strict:
            if kind == "centrifugal":
                if "amplitude" in params:
                    raise ServiceError("amplitude is unsupported for centrifugal loads")
                targets = params.get("targets", [])
                references = [] if not targets else self._references(targets, strict_targets=True)
                axis = self._references([params["axis"]], strict_targets=True)
                return {
                    "references": references,
                    "rotation_axis": axis,
                    "rotation_frequency_hz": self._finite_value(
                        params["rotation_frequency_hz"],
                        "rotation_frequency_hz",
                        strict_numeric=True,
                    ),
                }
            references = self._references(params.get("targets", []), strict_targets=True)
            data: dict[str, Any] = {"references": references}
            if kind == "transform":
                data["transform_type"] = params["transform_type"]
                if params["transform_type"] == "rectangular":
                    data["rotation_rad"] = self._finite_vector(
                        params["rotation_rad"], "rotation_rad", strict_numeric=True
                    )
                else:
                    data["base_point_m"] = self._finite_vector(
                        params["base_point_m"], "base_point_m", strict_numeric=True
                    )
                    data["axis_m"] = self._finite_vector(
                        params["axis_m"], "axis_m", strict_numeric=True
                    )
            elif kind == "force":
                data["force"] = self._finite_value(params["force_n"], "force_n", strict_numeric=True)
            elif kind == "pressure":
                data["pressure"] = self._finite_value(params["pressure_pa"], "pressure_pa", strict_numeric=True)
            elif kind == "selfweight":
                direction = self._finite_vector(params["acceleration_m_s2"], "acceleration_m_s2", strict_numeric=True)
                acceleration = math.sqrt(sum(component * component for component in direction))
                if acceleration <= 0.0:
                    raise ServiceError("acceleration_m_s2 must have a non-zero norm")
                data["gravity_acceleration"] = acceleration
                data["gravity_direction"] = direction
            elif kind == "displacement":
                displacement = (
                    self._finite_optional_vector(params["displacement_m"], "displacement_m", 1e9)
                    if params.get("displacement_m") is not None
                    else [None, None, None]
                )
                for axis, value in zip(("x", "y", "z"), displacement):
                    data[axis] = value
                    data[axis + "Free"] = value is None
                if params.get("rotation_rad") is not None:
                    rotation = self._finite_optional_vector(
                        params["rotation_rad"], "rotation_rad", 1e6
                    )
                    for axis, value in zip(("rotx", "roty", "rotz"), rotation):
                        data[axis] = value
                        data[axis + "Free"] = value is None
            elif kind == "pin":
                # Pin is a closed native preset.  The operation layer owns
                # every displacement DOF; do not forward implementation
                # fields that could let a direct/native caller override it.
                pass
            elif kind == "roller":
                axis = params.get("axis")
                if axis is None and "normal_m" in params:
                    normal = self._finite_vector(params["normal_m"], "normal_m", strict_numeric=True)
                    nonzero = [index for index, component in enumerate(normal) if component != 0.0]
                    if len(nonzero) != 1 or abs(normal[nonzero[0]]) != 1.0:
                        raise ServiceError("normal_m must be an axis-aligned unit vector")
                    axis = "xyz"[nonzero[0]]
                if axis not in {"x", "y", "z"}:
                    raise ServiceError("roller requires axis or normal_m")
                data["axis"] = axis
            if "amplitude" in params:
                if kind not in {"force", "pressure", "displacement"}:
                    raise ServiceError("amplitude is unsupported for this constraint kind")
                amplitude = self._validate_amplitude(params["amplitude"])
                if amplitude is not None:
                    data["amplitude"] = amplitude
            return data

        if "amplitude" in params:
            raise ServiceError("amplitude is unsupported for the compatibility constraint route")
        targets = self._compat_targets(params)
        # Even the compatibility route accepts only the public EntityRef
        # shape for nested targets.  The legacy aliases below remain supported,
        # but arbitrary nested native/property fields must not cross the bridge.
        data = {"references": self._references(targets, strict_targets=True)}
        if params.get("constraint_type") == "transform":
            data["transform_type"] = params["transform_type"]
            if params["transform_type"] == "rectangular":
                data["rotation_rad"] = self._finite_vector(
                    params["rotation_rad"], "rotation_rad", strict_numeric=True
                )
            else:
                data["base_point_m"] = self._finite_vector(
                    params["base_point_m"], "base_point_m", strict_numeric=True
                )
                data["axis_m"] = self._finite_vector(
                    params["axis_m"], "axis_m", strict_numeric=True
                )
        elif "force_n" in params:
            force = params["force_n"]
            if not isinstance(force, (list, tuple)) or force:
                data["force"] = self._compat_scalar(force, "force_n")
        if "pressure_pa" in params:
            pressure = params["pressure_pa"]
            if not isinstance(pressure, (list, tuple)) or pressure:
                data["pressure"] = self._compat_scalar(pressure, "pressure_pa")
        if "selfweight_acceleration_m_s2" in params:
            acceleration = params["selfweight_acceleration_m_s2"]
            if isinstance(acceleration, (list, tuple)) and not acceleration:
                acceleration = None
            if acceleration is None:
                pass
            elif isinstance(acceleration, (list, tuple)) and len(acceleration) == 3:
                direction = self._finite_vector(acceleration, "selfweight_acceleration_m_s2")
                data["gravity_acceleration"] = math.sqrt(sum(component * component for component in direction))
                data["gravity_direction"] = direction
            else:
                data["gravity_acceleration"] = self._compat_scalar(acceleration, "selfweight_acceleration_m_s2")
        if "displacement_m" in params:
            displacement_value = params["displacement_m"]
            if not (isinstance(displacement_value, (list, tuple)) and not displacement_value):
                displacement = self._finite_vector(displacement_value, "displacement_m")
                data.update({"x": displacement[0], "y": displacement[1], "z": displacement[2], "xFree": False, "yFree": False, "zFree": False})
        return data

    def _set_view(self, params: Mapping[str, Any]) -> None:
        gui = self.selection.gui
        if gui is None:
            try:
                import FreeCADGui as gui  # type: ignore
            except ImportError as exc:
                raise ServiceError("FreeCAD GUI is unavailable") from exc
        active_doc = getattr(gui, "activeDocument", lambda: None)() if gui is not None else None
        view = getattr(active_doc, "activeView", lambda: None)() if active_doc is not None else None
        if view is None:
            raise ServiceError("active view is unavailable")
        orientation = params.get("orientation")
        methods = {"front": "viewFront", "rear": "viewRear", "left": "viewLeft", "right": "viewRight", "top": "viewTop", "bottom": "viewBottom", "isometric": "viewAxonometric", "axonometric": "viewAxonometric"}
        if orientation is not None:
            if orientation not in methods:
                raise ServiceError("orientation is unsupported")
            callback = getattr(view, methods[orientation], None)
            if callable(callback):
                callback()
        if params.get("fit", False):
            fit = getattr(view, "fitAll", None)
            if callable(fit):
                fit()
