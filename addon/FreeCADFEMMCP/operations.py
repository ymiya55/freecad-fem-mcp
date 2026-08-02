"""Transactional, native FreeCAD FEM object operations.

Only public FreeCAD object APIs are used.  Legacy solver/tool modules are
intentionally not imported; CalculiX and Gmsh jobs are orchestrated by
``jobs.py``.
"""

from __future__ import annotations

import contextlib
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

from .version import host_version

try:
    import FreeCAD as _FreeCAD  # type: ignore
except ImportError:  # protocol/security tests do not install FreeCAD
    _FreeCAD = None
try:
    import ObjectsFem as _ObjectsFem  # type: ignore
except ImportError:
    _ObjectsFem = None
try:
    import femtools.checksanalysis as _checksanalysis  # type: ignore
except ImportError:
    _checksanalysis = None
try:
    import femtools.membertools as _membertools  # type: ignore
except ImportError:
    _membertools = None


class OperationError(RuntimeError):
    pass


class ValidationError(OperationError):
    pass


_CONSTRAINT_TYPES = {
    "fixed": "Fem::ConstraintFixed",
    "displacement": "Fem::ConstraintDisplacement",
    "force": "Fem::ConstraintForce",
    "pressure": "Fem::ConstraintPressure",
    "selfweight": "Fem::ConstraintSelfWeight",
}


def _finite_number(value: Any, name: str, minimum: Optional[float] = None) -> float:
    if isinstance(value, bool):
        raise OperationError("{} must be numeric".format(name))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OperationError("{} must be numeric".format(name)) from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise OperationError("{} is outside the allowed range".format(name))
    return number


def _safe_name(value: Any, default: str) -> str:
    if value is None:
        value = default
    if not isinstance(value, str) or not value or len(value) > 64:
        raise OperationError("object name is invalid")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in value):
        raise OperationError("object name contains invalid characters")
    return value


class FreeCADOperations:
    """Small native FEM facade with all mutating operations transactional."""

    def __init__(self, app: Any = None, gui: Any = None, objects_fem: Any = None, allowed_roots: Optional[Iterable[str]] = None):
        self.app = app if app is not None else _FreeCAD
        self.gui = gui
        self.objects_fem = objects_fem if objects_fem is not None else _ObjectsFem
        configured = list(allowed_roots) if allowed_roots is not None else self._configured_roots()
        self.allowed_roots = tuple(Path(root).resolve() for root in configured if isinstance(root, str) and root)
        self._revisions: dict[int, int] = {}

    def _configured_roots(self) -> list[str]:
        raw = os.environ.get("FREECAD_FEM_ALLOWED_ROOTS", "")
        if raw.strip():
            return [value for value in raw.split(os.pathsep) if value.strip()]
        app = self.app
        param_get = getattr(app, "ParamGet", None) if app is not None else None
        if callable(param_get):
            try:
                params = param_get("User parameter:BaseApp/Preferences/Mod/FreeCADFEMMCP")
                value = params.GetString("AllowedRoots", "")
                if value:
                    return [item for item in value.split(os.pathsep) if item.strip()]
            except Exception:
                pass
        return []

    def _require_app(self) -> Any:
        if self.app is None:
            raise OperationError("FreeCAD is not available")
        # Version checking is intentionally performed at the operation
        # boundary, not at protocol import time.
        try:
            host_version(self.app)
        except Exception as exc:
            raise OperationError(str(exc)) from exc
        return self.app

    def _document(self, document: Any = None) -> Any:
        app = self._require_app()
        doc = document if document is not None else getattr(app, "ActiveDocument", None)
        if doc is None:
            raise OperationError("an active document is required")
        return doc

    @staticmethod
    def _object_id(obj: Any) -> str:
        return str(getattr(obj, "Name", getattr(obj, "Label", "")))

    @staticmethod
    def fem_type(obj: Any) -> str:
        """Return the FEM semantic type for native or Python objects."""
        proxy = getattr(obj, "Proxy", None)
        return str(getattr(proxy, "Type", "") or getattr(obj, "TypeId", ""))

    @staticmethod
    def _find(doc: Any, name: str) -> Any:
        finder = getattr(doc, "getObject", None)
        if callable(finder):
            found = finder(name)
            if found is not None:
                return found
        for obj in getattr(doc, "Objects", []) or []:
            if getattr(obj, "Name", None) == name or getattr(obj, "Label", None) == name:
                return obj
        raise OperationError("object not found: {}".format(name))

    @contextlib.contextmanager
    def _transaction(self, doc: Any, label: str) -> Iterator[None]:
        opener = getattr(doc, "openTransaction", None)
        opened = False
        if callable(opener):
            opener(label)
            opened = True
        try:
            yield
        except Exception:
            abort = getattr(doc, "abortTransaction", None)
            if opened and callable(abort):
                abort()
            raise
        else:
            commit = getattr(doc, "commitTransaction", None)
            if opened and callable(commit):
                commit()
            key = id(doc)
            self._revisions[key] = self._revisions.get(key, 0) + 1

    def revision(self, document: Any = None) -> int:
        doc = self._document(document)
        return self._revisions.get(id(doc), 0)

    def active_document(self) -> Dict[str, Any]:
        doc = self._document()
        objects = []
        for obj in (getattr(doc, "Objects", []) or [])[:512]:
            objects.append({"name": getattr(obj, "Name", ""), "label": getattr(obj, "Label", ""), "type": getattr(obj, "TypeId", "")})
        return {"name": getattr(doc, "Name", ""), "label": getattr(doc, "Label", ""), "file": getattr(doc, "FileName", ""), "revision": str(self._revisions.get(id(doc), 0)), "objects": objects}

    def _document_path(self, path: Any) -> Path:
        if not isinstance(path, str) or not path or len(path) > 1024 or "\x00" in path:
            raise OperationError("document path is invalid")
        candidate = Path(path)
        if not candidate.is_absolute() or candidate.suffix.lower() not in {".fcstd", ".fcstd1"}:
            raise OperationError("document path must be an absolute FCStd path")
        if ".." in candidate.parts:
            raise OperationError("parent path components are not allowed")
        if candidate.is_dir():
            raise OperationError("document path is a directory")
        if any(part.is_symlink() for part in (candidate, *candidate.parents) if part.exists()):
            raise OperationError("reparse/symlink document paths are not allowed")
        if not self.allowed_roots:
            raise OperationError("no allowed document roots are configured")
        resolved = candidate.resolve()
        if not any(resolved == root or root in resolved.parents for root in self.allowed_roots):
            raise OperationError("document path is outside configured roots")
        return candidate

    def open_document(self, path: str) -> Dict[str, Any]:
        candidate = self._document_path(path)
        app = self._require_app()
        opener = getattr(app, "openDocument", None)
        if not callable(opener):
            raise OperationError("FreeCAD.openDocument is unavailable")
        doc = opener(str(candidate))
        return {"name": getattr(doc, "Name", ""), "label": getattr(doc, "Label", ""), "file": getattr(doc, "FileName", str(candidate))}

    def _new_object(self, doc: Any, type_id: str, name: str, helper: Optional[str] = None) -> Any:
        if helper and self.objects_fem is not None:
            function = getattr(self.objects_fem, helper, None)
            if callable(function):
                return function(doc, name)
        creator = getattr(doc, "addObject", None)
        if not callable(creator):
            raise OperationError("document.addObject is unavailable")
        return creator(type_id, name)

    @staticmethod
    def _add_to_analysis(analysis: Any, obj: Any) -> None:
        adder = getattr(analysis, "addObject", None)
        if callable(adder):
            adder(obj)
            return
        group = getattr(analysis, "Group", None)
        if isinstance(group, list):
            group.append(obj)

    def create_analysis(self, name: str = "Analysis") -> Dict[str, Any]:
        doc = self._document()
        safe = _safe_name(name, "Analysis")
        with self._transaction(doc, "Create FEM analysis"):
            analysis = self._new_object(doc, "Fem::FemAnalysis", safe, "makeAnalysis")
            # A public analysis always has a new CalculiX solver.  This avoids
            # accidental reuse of a stale/legacy solver object.
            solver = self._new_object(doc, "Fem::SolverCalculiX", "CalculiX", "makeSolverCalculiX")
            for key, value in (("AnalysisType", "static"), ("GeometricalNonlinearity", "linear"), ("MaterialNonlinearity", "linear")):
                try:
                    setattr(solver, key, value)
                except Exception:
                    pass
            self._add_to_analysis(analysis, solver)
        return {"name": self._object_id(analysis), "type": getattr(analysis, "TypeId", "Fem::FemAnalysis"), "solver": self._object_id(solver)}

    def set_material(self, analysis: str, material: Mapping[str, Any]) -> Dict[str, Any]:
        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        if not isinstance(material, Mapping):
            raise OperationError("material must be an object")
        name = _safe_name(material.get("name"), "MaterialSolid")
        young = _finite_number(material.get("youngs_modulus_pa", material.get("youngs_modulus", material.get("E", 210000000000.0))), "youngs_modulus", 0.0)
        poisson = _finite_number(material.get("poisson_ratio", material.get("nu", 0.3)), "poisson_ratio")
        density = _finite_number(material.get("density_kg_m3", material.get("density", 7850.0)), "density", 0.0)
        if not -1.0 < poisson < 0.5:
            raise OperationError("poisson_ratio must be between -1 and 0.5")
        with self._transaction(doc, "Set isotropic solid material"):
            obj = self._new_object(doc, "App::MaterialObjectPython", name, "makeMaterialSolid")
            # FreeCAD 1.1 stores isotropic material values in the Material
            # dictionary and expects unit-bearing strings.
            card = dict(getattr(obj, "Material", {}) or {})
            young_mpa = young / 1_000_000.0
            young_text = str(int(young_mpa)) if young_mpa.is_integer() else "{:.12g}".format(young_mpa)
            card.update({
                "Name": str(material.get("label", name)),
                "YoungsModulus": "{} MPa".format(young_text),
                "PoissonRatio": "{:.2f}".format(poisson),
                "Density": "{} kg/m^3".format(density),
            })
            try:
                obj.Material = card
            except Exception:
                for key, value in card.items():
                    try:
                        setattr(obj, key, value)
                    except Exception:
                        pass
            self._add_to_analysis(analysis_obj, obj)
        return {"name": self._object_id(obj), "youngs_modulus": young, "poisson_ratio": poisson, "density": density}

    def _references(self, doc: Any, raw: Any) -> list[tuple[Any, str]]:
        if not isinstance(raw, list) or not raw or len(raw) > 128:
            raise OperationError("references must be a non-empty list")
        references = []
        for item in raw:
            if isinstance(item, dict):
                object_name, sub = item.get("object"), item.get("sub_element", item.get("subelement"))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                object_name, sub = item
            else:
                raise OperationError("reference must identify an object and sub-element")
            if not isinstance(object_name, str) or not isinstance(sub, str) or len(sub) > 128:
                raise OperationError("reference is invalid")
            references.append((self._find(doc, object_name), sub))
        return references

    def _vector(self, value: Any) -> Any:
        if isinstance(value, (list, tuple)) and len(value) == 3:
            values = tuple(_finite_number(item, "vector component") for item in value)
            vector_cls = getattr(self.app, "Vector", None)
            if callable(vector_cls):
                return vector_cls(*values)
            return values
        raise OperationError("vector must have three numeric components")

    @staticmethod
    def _unit_value(value: Any, unit: str, name: str) -> str:
        return "{} {}".format(_finite_number(value, name), unit)

    def add_constraint(self, analysis: str, kind: str, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        if kind not in _CONSTRAINT_TYPES:
            raise OperationError("unsupported constraint kind")
        data = dict(params or {})
        name = _safe_name(data.pop("name", "Constraint_" + kind), "Constraint_" + kind)
        raw_references = data.pop("references", data.pop("refs", None))
        # FreeCAD 1.1's ConstraintSelfWeight is a global load object and does
        # not expose a References property.  In particular, an empty GUI
        # selection is valid for gravity; all other constraint kinds still
        # require resolved entity references.
        references = [] if kind == "selfweight" else self._references(doc, raw_references)
        helper = {
            "fixed": "makeConstraintFixed", "displacement": "makeConstraintDisplacement",
            "force": "makeConstraintForce", "pressure": "makeConstraintPressure",
            "selfweight": "makeConstraintSelfWeight",
        }[kind]
        with self._transaction(doc, "Add {} constraint".format(kind)):
            obj = self._new_object(doc, _CONSTRAINT_TYPES[kind], name, helper)
            if kind != "selfweight":
                try:
                    obj.References = references
                except Exception:
                    pass
            if kind == "fixed":
                pass
            elif kind == "displacement":
                for axis in "xyz":
                    free_key, value_key = axis + "Free", axis
                    if free_key in data:
                        setattr(obj, free_key, bool(data[free_key]))
                    if value_key in data and not bool(data.get(free_key, False)):
                        # FreeCAD 1.1.x exposes displacement values as
                        # xDisplacement/yDisplacement/zDisplacement.  The
                        # service's internal x/y/z keys remain stable, but
                        # must not be assigned as native properties.
                        native_key = axis + "Displacement"
                        setattr(obj, native_key, self._unit_value(data[value_key], "m", value_key))
            elif kind == "force":
                if "force" in data:
                    obj.Force = self._unit_value(data["force"], "N", "force")
                if "direction" in data:
                    obj.DirectionVector = self._vector(data["direction"])
                if "reversed" in data:
                    obj.Reversed = bool(data["reversed"])
            elif kind == "pressure":
                if "pressure" in data:
                    obj.Pressure = self._unit_value(data["pressure"], "Pa", "pressure")
                if "reversed" in data:
                    obj.Reversed = bool(data["reversed"])
            elif kind == "selfweight":
                if "gravity_acceleration" in data:
                    obj.GravityAcceleration = self._unit_value(data["gravity_acceleration"], "m/s^2", "gravity_acceleration")
                if "gravity_direction" in data:
                    obj.GravityDirection = self._vector(data["gravity_direction"])
            self._add_to_analysis(analysis_obj, obj)
        return {"name": self._object_id(obj), "kind": kind}

    @staticmethod
    def _remote_subshape_kind(subelement: str) -> Optional[str]:
        """Return the declared TopoShape kind for a ``Face1``-style name."""

        for prefix in ("Vertex", "Edge", "Face"):
            suffix = subelement[len(prefix):] if subelement.startswith(prefix) else ""
            if suffix and suffix.isascii() and suffix.isdigit() and int(suffix) > 0:
                return prefix
        return None

    @classmethod
    def _validate_remote_references(cls, references: list[tuple[Any, str]]) -> None:
        """Resolve every remote target against its native TopoShape.

        ``Fem::ConstraintRigidBody`` accepts only actual vertex, edge, or face
        references.  Checking through ``Shape.getElement`` before object
        creation rejects stale/forged names and prevents a mixed-shape rigid
        body that the GUI would not permit.
        """

        shape_kind: Optional[str] = None
        for obj, subelement in references:
            shape = getattr(obj, "Shape", None)
            if shape is None:
                raise OperationError("remote load target has no Shape")
            is_null = getattr(shape, "isNull", None)
            try:
                if (callable(is_null) and is_null()) or (isinstance(is_null, bool) and is_null):
                    raise OperationError("remote load target Shape is null")
            except OperationError:
                raise
            except Exception as exc:
                raise OperationError("remote load target Shape is invalid") from exc

            declared_kind = cls._remote_subshape_kind(subelement)
            if declared_kind is None:
                raise OperationError("remote load subelement is invalid")
            getter = getattr(shape, "getElement", None)
            if not callable(getter):
                raise OperationError("remote load target Shape cannot resolve subelements")
            try:
                element = getter(subelement)
            except Exception as exc:
                raise OperationError("remote load subelement does not exist") from exc
            if element is None:
                raise OperationError("remote load subelement does not exist")
            element_is_null = getattr(element, "isNull", None)
            try:
                if (callable(element_is_null) and element_is_null()) or (
                    isinstance(element_is_null, bool) and element_is_null
                ):
                    raise OperationError("remote load subelement does not exist")
            except OperationError:
                raise
            except Exception as exc:
                raise OperationError("remote load subelement is invalid") from exc
            actual_kind = getattr(element, "ShapeType", None)
            if callable(actual_kind):
                actual_kind = actual_kind()
            if str(actual_kind) != declared_kind:
                raise OperationError("remote load subelement type does not match its name")
            if shape_kind is None:
                shape_kind = declared_kind
            elif shape_kind != declared_kind:
                raise OperationError("remote load targets must use one shape type")

    @staticmethod
    def _remote_vector(
        data: Mapping[str, Any], key: str, limit: float, *, required: bool = False
    ) -> tuple[float, float, float]:
        """Read one strict, bounded SI vector for a rigid-body remote load."""

        value = data.get(key)
        if value is None:
            if required:
                raise OperationError("{} is required".format(key))
            return (0.0, 0.0, 0.0)
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise OperationError("{} must contain exactly three components".format(key))
        values: list[float] = []
        for component in value:
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                raise OperationError("{} must be numeric".format(key))
            number = float(component)
            if not math.isfinite(number) or abs(number) > limit:
                raise OperationError("{} is outside the allowed range".format(key))
            values.append(number)
        return (values[0], values[1], values[2])

    def add_remote_load(self, analysis: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        """Create a native ``Fem::ConstraintRigidBody`` remote load.

        The public service supplies global SI vectors.  FreeCAD's native FEM
        object stores the reference node in millimetres and accepts force and
        moment values as unit-bearing quantities, so conversion is kept here at
        the native operation boundary.
        """

        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        if not isinstance(params, Mapping):
            raise OperationError("remote load parameters must be an object")
        raw_references = params.get("references")
        references = self._references(doc, raw_references)
        self._validate_remote_references(references)
        reference_point_m = self._remote_vector(params, "reference_point_m", 1e9, required=True)
        force_n = self._remote_vector(params, "force_n", 1e15)
        moment_n_m = self._remote_vector(params, "moment_n_m", 1e15)
        if not any(component != 0.0 for component in (*force_n, *moment_n_m)):
            raise OperationError("force_n or moment_n_m must contain a non-zero component")
        name = _safe_name(params.get("name"), "RemoteLoad")

        with self._transaction(doc, "Add remote load"):
            obj = self._new_object(doc, "Fem::ConstraintRigidBody", name, "makeConstraintRigidBody")
            try:
                obj.References = references
            except Exception as exc:
                raise OperationError("remote load references are invalid") from exc
            # FreeCAD's PropertyPosition uses the document's native length
            # unit (millimetres), while the public API is explicitly metres.
            obj.ReferenceNode = self._vector(tuple(component * 1000.0 for component in reference_point_m))

            force_axes = ("X", "Y", "Z")
            for axis, component in zip(force_axes, force_n):
                setattr(obj, "Force" + axis, self._unit_value(component, "N", "force_n"))
                setattr(obj, "TranslationalMode" + axis, "Load" if component != 0.0 else "Free")
            for axis, component in zip(force_axes, moment_n_m):
                setattr(obj, "Moment" + axis, self._unit_value(component, "N*m", "moment_n_m"))
                setattr(obj, "RotationalMode" + axis, "Load" if component != 0.0 else "Free")
            self._add_to_analysis(analysis_obj, obj)
        return {"name": self._object_id(obj), "kind": "remote_load"}

    def create_mesh(self, analysis: str, name: str = "GmshMesh", **settings: Any) -> Dict[str, Any]:
        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        safe = _safe_name(name, "GmshMesh")
        with self._transaction(doc, "Create Gmsh mesh"):
            obj = self._new_object(doc, "Fem::FemMeshGmsh", safe, "makeMeshGmsh")
            shape_name = settings.get("shape", settings.get("geometry"))
            if shape_name is not None:
                geometry = self._find(doc, shape_name)
                if not hasattr(geometry, "Shape"):
                    raise OperationError("mesh shape object has no Shape")
                # FreeCAD 1.1's Fem::FemMeshGmsh Shape property is an
                # App::PropertyLink to the geometry object, not a TopoShape.
                obj.Shape = geometry
            for key in ("MaxSize", "MinSize", "CharacteristicLengthMax", "CharacteristicLengthMin", "ElementOrder", "SecondOrderLinear", "Algorithm2D", "Algorithm3D"):
                if key in settings:
                    value = settings[key]
                    if key in {"MaxSize", "MinSize", "CharacteristicLengthMax", "CharacteristicLengthMin"}:
                        value = _finite_number(value, key, 0.0)
                    if key == "ElementOrder":
                        if value in {1, "1", "1st", "first"}:
                            value = "1st"
                        elif value in {2, "2", "2nd", "second"}:
                            value = "2nd"
                        else:
                            raise OperationError("ElementOrder must be 1st or 2nd")
                    setattr(obj, key, value)
            self._add_to_analysis(analysis_obj, obj)
        return {"name": self._object_id(obj), "type": getattr(obj, "TypeId", "Fem::FemMeshGmsh")}

    def _create_solver(self, analysis: str, name: str = "CalculiX", working_directory: Optional[str] = None) -> Dict[str, Any]:
        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        safe = _safe_name(name, "CalculiX")
        with self._transaction(doc, "Create CalculiX solver"):
            solver = self._new_object(doc, "Fem::SolverCalculiX", safe, "makeSolverCalculiX")
            try:
                solver.AnalysisType = "static"
            except Exception:
                pass
            if working_directory is not None:
                if not isinstance(working_directory, str) or len(working_directory) > 1024 or "\x00" in working_directory:
                    raise OperationError("working directory is invalid")
                path = Path(working_directory)
                if not path.is_absolute() or not path.exists() or not path.is_dir():
                    raise OperationError("working directory must be an existing absolute directory")
                try:
                    solver.WorkingDirectory = str(path)
                except Exception:
                    pass
            self._add_to_analysis(analysis_obj, solver)
        return {"name": self._object_id(solver), "type": getattr(solver, "TypeId", "Fem::SolverCalculiX"), "analysis_type": "static"}

    def validate(self, analysis: str) -> Dict[str, Any]:
        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        members = list(getattr(analysis_obj, "Group", []) or [])
        solver = next((item for item in members if self.fem_type(item) == "Fem::SolverCalculiX"), None)
        mesh = next((item for item in members if "FemMesh" in getattr(item, "TypeId", "")), None)
        diagnostics: list[Any] = []
        if solver is None:
            diagnostics.append("analysis has no CalculiX solver")
        if mesh is None:
            diagnostics.append("analysis has no mesh")
        if solver is not None and mesh is not None and _checksanalysis is not None and _membertools is not None:
            try:
                member = _membertools.AnalysisMember(analysis_obj)
                checked = _checksanalysis.check_member_for_solver_calculix(analysis_obj, solver, mesh, member)
                if isinstance(checked, tuple) and len(checked) == 2 and isinstance(checked[0], bool):
                    if not checked[0] and checked[1]:
                        diagnostics.append(checked[1])
                elif checked:
                    diagnostics.extend(checked if isinstance(checked, (list, tuple)) else [checked])
            except Exception as exc:
                diagnostics.append(str(exc))
        else:
            kinds = {str(getattr(item, "TypeId", "")) for item in members}
            if not any("Material" in kind for kind in kinds):
                diagnostics.append("analysis has no material")
            if not any("Constraint" in kind for kind in kinds):
                diagnostics.append("analysis has no constraints")
        return {"valid": not diagnostics, "diagnostics": diagnostics, "analysis": self._object_id(analysis_obj), "solver": self._object_id(solver) if solver else None, "mesh": self._object_id(mesh) if mesh else None}

    def save_document(self, path: Optional[str] = None, overwrite: bool = False) -> Dict[str, Any]:
        doc = self._document()
        if path is None:
            current = getattr(doc, "FileName", "")
            if not current:
                raise OperationError("a new document requires an explicit path")
            candidate = Path(current)
        else:
            candidate = self._document_path(path)
        existed = candidate.exists()
        if existed and not overwrite:
            raise OperationError("refusing to overwrite existing document without overwrite=true")
        saver = getattr(doc, "saveAs", None)
        if not callable(saver):
            raise OperationError("document.saveAs is unavailable")
        saver(str(candidate))
        return {"file": str(candidate), "overwritten": bool(existed and overwrite), "revision": str(self._revisions.get(id(doc), 0))}
