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
        {"action", "document_id", "name", "solver", "analysis_type"},
        {"action"},
    ),
    ("material", "assign"): (
        {
            "action", "document_id", "analysis_id", "material_id", "name",
            "youngs_modulus_pa", "poisson_ratio", "density_kg_m3", "yield_strength_pa",
        },
        {"action", "analysis_id"},
    ),
    ("mesh", "create"): (
        {"action", "document_id", "analysis_id", "element_size_mm", "second_order", "shape_id"},
        {"action", "analysis_id"},
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
        {"action", "analysis_id", "field", "max_items"},
        {"action", "analysis_id"},
    ),
    ("results", "show"): (
        {"action", "analysis_id", "field", "max_items", "frame"},
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
            if params.get("analysis_type", "static") != "static":
                raise ServiceError("analysis_type is unsupported")
            return
        if method == "material":
            cls._require_identifier(params, "analysis_id")
            cls._optional_text(params, "material_id")
            cls._optional_text(params, "name")
            cls._optional_finite(params, "youngs_modulus_pa", positive=True)
            cls._optional_finite(params, "poisson_ratio")
            if "poisson_ratio" in params and params["poisson_ratio"] is not None and not -1.0 < params["poisson_ratio"] < 0.5:
                raise ServiceError("poisson_ratio is outside the allowed range")
            cls._optional_finite(params, "density_kg_m3", positive=True)
            cls._optional_finite(params, "yield_strength_pa", positive=True)
            return
        if method == "mesh":
            cls._require_identifier(params, "analysis_id")
            cls._optional_finite(params, "element_size_mm", positive=True)
            if "second_order" in params:
                cls._strict_bool(params["second_order"], "second_order")
            cls._optional_text(params, "shape_id")
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
            if action == "show" and "frame" in params:
                cls._strict_int(params["frame"], "frame", 0, 100000)

    def _validate_constraint_contract(self, params: Mapping[str, Any]) -> None:
        # Keep the documented legacy target aliases, but do not permit an
        # arbitrary native property/name/code field through this compatibility
        # method.  Typed routes use the narrower contracts above.
        allowed = {
            "action", "document_id", "analysis_id", "constraint_id", "constraint_type",
            "targets", "displacement_m", "force_n", "pressure_pa",
            "selfweight_acceleration_m_s2", "object_name", "subelements",
        }
        self._validate_fields(params, allowed, {"action", "analysis_id", "constraint_type"})
        self._require_identifier(params, "analysis_id")
        if "document_id" in params:
            self._require_identifier(params, "document_id")
        if params["constraint_type"] not in {"fixed", "displacement", "force", "pressure", "selfweight"}:
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
                    "analysis_types": ["static"],
                    "loads": [
                        "force", "pressure", "gravity", "acceleration", "centrifugal",
                        "remote_force", "remote_moment",
                    ],
                    "boundary_conditions": ["fixed", "displacement", "remote_displacement"],
                    "connections": [],
                    "mpc_types": [],
                    "result_kinds": ["displacement", "stress", "strain", "von_mises", "reaction"],
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
            result = self.operations.create_analysis(params.get("name", "Analysis"))
            return {"analysis_id": result["name"], **result}

        if method == "material":
            self._action(params, "assign")
            material = dict(params)
            nested = params.get("material")
            if isinstance(nested, Mapping):
                material.update(nested)
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
            return self.operations.validate(params.get("analysis_id"))

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
            if params.get("analysis_id"):
                solver = self._solver(self._analysis(params.get("analysis_id")))
            elif params.get("job_id"):
                solver = self.jobs.native_object(params.get("job_id"))
            else:
                raise ServiceError("analysis_id or job_id is required")
            results = getattr(solver, "Results", None)
            if results is None:
                raise ServiceError("solver has no imported results")
            limit = int(params.get("max_items", 8192))
            if action == "get":
                return self.pipeline.query_native(results, params.get("field"), int(params.get("frame", 0)), limit)
            return self.pipeline.show_native(results, params.get("field"), int(params.get("frame", 0)), limit)

        raise ServiceError("method is not implemented")

    def _references(self, targets: Any, *, strict_targets: bool = False) -> list[dict[str, str]]:
        if not targets:
            captured = self.selection.capture()
            return [{"object": item["object"], "sub_element": sub}
                    for item in captured["items"] for sub in item.get("sub_elements", [])]
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
        if boundary_type not in {"fixed", "displacement"}:
            raise ServiceError("boundary_type is unsupported")
        allowed = {"action", "document_id", "analysis_id", "targets", "boundary_type"}
        required = {"action", "analysis_id", "boundary_type"}
        if boundary_type == "displacement":
            allowed.add("displacement_m")
            required.add("displacement_m")
        self._validate_fields(params, allowed, required)
        self._require_identifier(params, "analysis_id")
        if "document_id" in params:
            self._require_identifier(params, "document_id")
        if "targets" in params and not isinstance(params["targets"], list):
            raise ServiceError("targets must be a bounded list")
        if boundary_type == "displacement":
            self._finite_vector(params["displacement_m"], "displacement_m", strict_numeric=True)
        return boundary_type

    def _validate_remote_load_request(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Validate the strict global remote-force/moment request shape."""

        allowed = {
            "action", "document_id", "analysis_id", "targets", "reference_point_m",
            "force_n", "moment_n_m",
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
        return data

    def _validate_remote_displacement_request(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Validate a rigid-body kinematic reference-point request."""

        allowed = {
            "action", "document_id", "analysis_id", "targets", "reference_point_m",
            "translation_m", "rotation_rad",
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
        return data

    def _constraint_data(self, params: Mapping[str, Any], kind: Any, *, strict: bool) -> dict[str, Any]:
        """Build native constraint data for both the compatibility and typed routes.

        Target resolution and conversion to native SI fields intentionally live
        here so ``constraint``, ``load`` and ``boundary_condition`` cannot drift
        in their handling of GUI selection, references, or vectors.
        """
        if strict:
            if kind == "centrifugal":
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
            if kind == "force":
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
                displacement = self._finite_vector(params["displacement_m"], "displacement_m", strict_numeric=True)
                data.update({"x": displacement[0], "y": displacement[1], "z": displacement[2], "xFree": False, "yFree": False, "zFree": False})
            return data

        targets = self._compat_targets(params)
        # Even the compatibility route accepts only the public EntityRef
        # shape for nested targets.  The legacy aliases below remain supported,
        # but arbitrary nested native/property fields must not cross the bridge.
        data = {"references": self._references(targets, strict_targets=True)}
        if "force_n" in params:
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
