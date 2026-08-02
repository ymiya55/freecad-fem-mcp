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

    def __call__(self, request: Request) -> Any:
        params = request.params
        method = request.method
        if not isinstance(params, Mapping):
            raise ServiceError("params must be an object")
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
            return {"ready": True, "version": version}

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
            constraint = dict(params)
            targets = params.get("targets", [])
            if not targets and params.get("object_name"):
                targets = [{"object_name": params["object_name"], "subelements": params.get("subelements", [])}]
            constraint["references"] = self._references(targets)
            if "force_n" in params:
                force = params["force_n"]
                constraint["force"] = force[0] if isinstance(force, (list, tuple)) and force else force
            if "pressure_pa" in params:
                pressure = params["pressure_pa"]
                constraint["pressure"] = pressure[0] if isinstance(pressure, (list, tuple)) and pressure else pressure
            if "selfweight_acceleration_m_s2" in params:
                acceleration = params["selfweight_acceleration_m_s2"]
                if isinstance(acceleration, (list, tuple)) and len(acceleration) == 3:
                    constraint["gravity_acceleration"] = math.sqrt(sum(float(item) * float(item) for item in acceleration))
                    constraint["gravity_direction"] = list(acceleration)
                else:
                    constraint["gravity_acceleration"] = acceleration[0] if isinstance(acceleration, (list, tuple)) and acceleration else acceleration
            displacement = params.get("displacement_m")
            if isinstance(displacement, (list, tuple)) and len(displacement) == 3:
                constraint.update({"x": displacement[0], "y": displacement[1], "z": displacement[2], "xFree": False, "yFree": False, "zFree": False})
            result = self.operations.add_constraint(params.get("analysis_id"), params.get("constraint_type"), constraint)
            return {"constraint_id": result["name"], **result}

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

    def _references(self, targets: Any) -> list[dict[str, str]]:
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
            subelements = target.get("subelements", [])
            if not isinstance(subelements, list) or len(subelements) > 64:
                raise ServiceError("target subelements are invalid")
            for subelement in subelements:
                if not isinstance(subelement, str) or len(subelement) > 128:
                    raise ServiceError("target subelement is invalid")
                references.append({"object": target["object_name"], "sub_element": subelement})
        return references

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
