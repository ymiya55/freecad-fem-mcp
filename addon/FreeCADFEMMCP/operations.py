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

    @staticmethod
    def _strict_analysis_number(
        value: Any, name: str, minimum: float, maximum: float
    ) -> float:
        """Validate an analysis control without coercing JSON strings/bools."""

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise OperationError("{} must be numeric".format(name))
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise OperationError("{} must be numeric".format(name)) from exc
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise OperationError("{} is outside the allowed range".format(name))
        return number

    @classmethod
    def _analysis_options(
        cls,
        analysis_type: Any,
        eigenmodes_count: Any = None,
        frequency_low_hz: Any = None,
        frequency_high_hz: Any = None,
        buckling_factors: Any = None,
        buckling_accuracy: Any = None,
    ) -> dict[str, Any]:
        """Validate and normalize the closed SolverCalculiX mode contract."""

        if not isinstance(analysis_type, str) or analysis_type not in {"static", "frequency", "buckling"}:
            raise OperationError("analysis_type is unsupported")

        frequency_fields = (eigenmodes_count, frequency_low_hz, frequency_high_hz)
        buckling_fields = (buckling_factors, buckling_accuracy)
        if analysis_type == "static":
            if any(value is not None for value in (*frequency_fields, *buckling_fields)):
                raise OperationError("static analysis does not accept analysis-specific fields")
        elif analysis_type == "frequency":
            if isinstance(eigenmodes_count, bool) or not isinstance(eigenmodes_count, int):
                raise OperationError("eigenmodes_count is required for frequency analysis")
            if not 1 <= eigenmodes_count <= 100:
                raise OperationError("eigenmodes_count is outside the allowed range")
            if (frequency_low_hz is None) != (frequency_high_hz is None):
                raise OperationError(
                    "frequency_low_hz and frequency_high_hz must be provided together"
                )
            if any(value is not None for value in buckling_fields):
                raise OperationError("frequency analysis does not accept buckling fields")
            if frequency_low_hz is not None:
                low = cls._strict_analysis_number(
                    frequency_low_hz, "frequency_low_hz", 0.0, 1e9
                )
                high = cls._strict_analysis_number(
                    frequency_high_hz, "frequency_high_hz", 0.0, 1e9
                )
                if high <= low:
                    raise OperationError("frequency_high_hz must be greater than frequency_low_hz")
            else:
                # Native CalculiX uses zero limits when no frequency range is
                # supplied.  Keep these explicit so every native mode has a
                # deterministic setting.
                low = high = 0.0
        else:  # buckling
            if isinstance(buckling_factors, bool) or not isinstance(buckling_factors, int):
                raise OperationError("buckling_factors is required for buckling analysis")
            if not 1 <= buckling_factors <= 100:
                raise OperationError("buckling_factors is outside the allowed range")
            accuracy = cls._strict_analysis_number(
                buckling_accuracy, "buckling_accuracy", 0.0, 1.0
            )
            if accuracy <= 0.0:
                raise OperationError("buckling_accuracy must be positive")
            if any(value is not None for value in frequency_fields):
                raise OperationError("buckling analysis does not accept frequency fields")

        return {
            "analysis_type": analysis_type,
            "eigenmodes_count": eigenmodes_count,
            "frequency_low_hz": low if analysis_type == "frequency" else None,
            "frequency_high_hz": high if analysis_type == "frequency" else None,
            "buckling_factors": buckling_factors if analysis_type == "buckling" else None,
            "buckling_accuracy": accuracy if analysis_type == "buckling" else None,
        }

    @staticmethod
    def _native_property_name(obj: Any, *names: str) -> str:
        for name in names:
            try:
                if hasattr(obj, name):
                    return name
            except Exception:
                # A native property lookup may raise for an unsupported
                # alias; leave the loop to probe the next known spelling.
                pass
        raise OperationError("native solver property is unavailable: {}".format("/".join(names)))

    @classmethod
    def _set_native_required(cls, obj: Any, name: str, value: Any) -> None:
        # Checking first is intentional: regular Python fakes allow arbitrary
        # attributes, whereas native FreeCAD properties are a closed schema.
        cls._native_property_name(obj, name)
        try:
            setattr(obj, name, value)
        except Exception as exc:
            raise OperationError("native solver property cannot be set: {}".format(name)) from exc

    def _frequency_quantity(self, value: float) -> Any:
        text = "{} Hz".format(format(value, ".17g"))
        units = getattr(self.app, "Units", None)
        quantity = getattr(units, "Quantity", None) if units is not None else None
        if callable(quantity):
            try:
                return quantity(text)
            except Exception:
                # Test doubles and old FreeCAD versions may not expose a
                # Quantity constructor; the native setter still accepts the
                # unit-bearing string on those versions.
                pass
        return text

    def create_analysis(
        self,
        name: str = "Analysis",
        analysis_type: str = "static",
        *,
        eigenmodes_count: Any = None,
        frequency_low_hz: Any = None,
        frequency_high_hz: Any = None,
        buckling_factors: Any = None,
        buckling_accuracy: Any = None,
    ) -> Dict[str, Any]:
        doc = self._document()
        safe = _safe_name(name, "Analysis")
        options = self._analysis_options(
            analysis_type,
            eigenmodes_count,
            frequency_low_hz,
            frequency_high_hz,
            buckling_factors,
            buckling_accuracy,
        )
        with self._transaction(doc, "Create FEM analysis"):
            analysis = self._new_object(doc, "Fem::FemAnalysis", safe, "makeAnalysis")
            # A public analysis always has a new CalculiX solver.  This avoids
            # accidental reuse of a stale/legacy solver object.
            solver = self._new_object(doc, "Fem::SolverCalculiX", "CalculiX", "makeSolverCalculiX")
            # Required mode properties are set before the solver is attached
            # to the analysis.  Any missing property or rejected value raises,
            # and _transaction aborts the whole native operation.
            self._set_native_required(solver, "AnalysisType", options["analysis_type"])
            if options["analysis_type"] == "frequency":
                self._set_native_required(
                    solver, "EigenmodesCount", options["eigenmodes_count"]
                )
                low_name = self._native_property_name(
                    solver, "EigenmodeLow", "EigenmodeLowLimit"
                )
                high_name = self._native_property_name(
                    solver, "EigenmodeHigh", "EigenmodeHighLimit"
                )
                self._set_native_required(
                    solver, low_name, self._frequency_quantity(options["frequency_low_hz"])
                )
                self._set_native_required(
                    solver, high_name, self._frequency_quantity(options["frequency_high_hz"])
                )
            elif options["analysis_type"] == "buckling":
                self._set_native_required(solver, "BucklingFactors", options["buckling_factors"])
                self._set_native_required(solver, "BucklingAccuracy", options["buckling_accuracy"])

            # These controls are present on current CalculiX objects but are
            # not mode-specific.  Keep compatibility with older native builds
            # by assigning them only when available.
            for key, value in (("GeometricalNonlinearity", "linear"), ("MaterialNonlinearity", "linear")):
                try:
                    if hasattr(solver, key):
                        setattr(solver, key, value)
                except Exception:
                    pass
            self._add_to_analysis(analysis, solver)
        return {
            "name": self._object_id(analysis),
            "type": getattr(analysis, "TypeId", "Fem::FemAnalysis"),
            "solver": self._object_id(solver),
            "analysis_type": options["analysis_type"],
        }

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

    @staticmethod
    def _normalize_amplitude(value: Any) -> Optional[list[tuple[float, float]]]:
        """Validate and normalize a public amplitude sequence.

        Amplitudes are deliberately handled at the native operation boundary
        rather than copied onto the object as a client-provided property.  A
        strict list/object/numeric shape here keeps direct addon callers on
        the same contract as the MCP models and leaves only canonical
        ``(time_s, scale)`` pairs for native property assignment.
        """

        if value is None:
            return None
        if not isinstance(value, list) or not 2 <= len(value) <= 256:
            raise OperationError("amplitude must contain between 2 and 256 points")

        points: list[tuple[float, float]] = []
        previous_time: Optional[float] = None
        for index, point in enumerate(value):
            if not isinstance(point, Mapping) or set(point) != {"time_s", "scale"}:
                raise OperationError("amplitude point must contain exactly time_s and scale")
            raw_time = point["time_s"]
            raw_scale = point["scale"]
            if isinstance(raw_time, bool) or not isinstance(raw_time, (int, float)):
                raise OperationError("amplitude time_s must be numeric")
            if isinstance(raw_scale, bool) or not isinstance(raw_scale, (int, float)):
                raise OperationError("amplitude scale must be numeric")
            try:
                time_s = float(raw_time)
                scale = float(raw_scale)
            except (TypeError, ValueError, OverflowError) as exc:
                raise OperationError("amplitude point must be numeric") from exc
            if not math.isfinite(time_s) or not 0.0 <= time_s <= 1e12:
                raise OperationError("amplitude time_s is outside the allowed range")
            if not math.isfinite(scale) or abs(scale) > 1e9:
                raise OperationError("amplitude scale is outside the allowed range")
            if index == 0 and time_s != 0.0:
                raise OperationError("amplitude first time_s must be exactly 0.0")
            if previous_time is not None and time_s <= previous_time:
                raise OperationError("amplitude time_s values must be strictly increasing")
            points.append((time_s, scale))
            previous_time = time_s
        return points

    @classmethod
    def _apply_amplitude(cls, obj: Any, amplitude: list[tuple[float, float]]) -> None:
        """Attach a validated amplitude to a native FEM object.

        FreeCAD exposes these fields only on load/constraint objects that
        support amplitudes.  Missing fields are an operation error, allowing
        the surrounding transaction to abort before the object is added to
        the analysis.  The wire values are formatted exactly as CalculiX's
        ``time, scale`` amplitude rows and never pass through as client
        strings.
        """

        if not hasattr(obj, "EnableAmplitude") or not hasattr(obj, "AmplitudeValues"):
            raise OperationError("native object does not support amplitudes")
        rows = [
            format(time_s, ".17g") + ", " + format(scale, ".17g")
            for time_s, scale in amplitude
        ]
        try:
            setattr(obj, "EnableAmplitude", True)
            setattr(obj, "AmplitudeValues", rows)
        except Exception as exc:
            raise OperationError("native amplitude properties are unavailable") from exc

    def add_constraint(self, analysis: str, kind: str, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        if kind not in _CONSTRAINT_TYPES:
            raise OperationError("unsupported constraint kind")
        data = dict(params or {})
        amplitude_present = "amplitude" in data
        amplitude = data.pop("amplitude", None)
        if amplitude_present and kind not in {"force", "pressure", "displacement"}:
            raise OperationError("amplitude is unsupported for this constraint kind")
        normalized_amplitude = self._normalize_amplitude(amplitude)
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
            if normalized_amplitude is not None:
                self._apply_amplitude(obj, normalized_amplitude)
            self._add_to_analysis(analysis_obj, obj)
        return {"name": self._object_id(obj), "kind": kind}

    @staticmethod
    def _connection_factory(objects_fem: Any, helper: str, doc: Any, name: str) -> Any:
        """Create a tie/contact object only through its verified FEM factory."""

        factory = getattr(objects_fem, helper, None) if objects_fem is not None else None
        if not callable(factory):
            raise OperationError("native connection factory is unavailable: {}".format(helper))
        try:
            obj = factory(doc, name)
        except Exception as exc:
            raise OperationError("native connection factory failed: {}".format(helper)) from exc
        if obj is None:
            raise OperationError("native connection factory returned no object")
        return obj

    @staticmethod
    def _set_connection_property(obj: Any, name: str, value: Any) -> None:
        try:
            if not hasattr(obj, name):
                raise OperationError("native connection property is unavailable: {}".format(name))
            setattr(obj, name, value)
        except OperationError:
            raise
        except Exception as exc:
            raise OperationError("native connection property cannot be set: {}".format(name)) from exc

    @classmethod
    def _validate_connection_faces(cls, references: list[tuple[Any, str]]) -> None:
        """Require two distinct, live native FaceN references in slave/master order."""

        if not isinstance(references, list) or len(references) != 2:
            raise OperationError("connection requires exactly one slave and one master face")
        first_obj, first_face = references[0]
        second_obj, second_face = references[1]
        for subelement in (first_face, second_face):
            if not isinstance(subelement, str) or not subelement.startswith("Face"):
                raise OperationError("connection references must use FaceN")
            suffix = subelement[4:]
            if (
                not suffix
                or not suffix.isascii()
                or not suffix.isdigit()
                or int(suffix) <= 0
                or (len(suffix) > 1 and suffix.startswith("0"))
            ):
                raise OperationError("connection references must use FaceN")
        if (
            first_obj is second_obj
            and first_face == second_face
        ) or (
            cls._object_id(first_obj) == cls._object_id(second_obj)
            and first_face == second_face
        ):
            raise OperationError("slave and master faces must be distinct")
        # Reuse the native Shape/getElement checks for stale references and
        # verify the actual TopoShape type, rather than trusting FaceN text.
        cls._validate_remote_references(references)

    @classmethod
    def _validate_connection_references(cls, references: list[tuple[Any, str]]) -> None:
        """Compatibility name for callers performing native pre-validation."""

        cls._validate_connection_faces(references)

    @staticmethod
    def _analysis_solver(analysis_obj: Any) -> Any:
        for member in list(getattr(analysis_obj, "Group", []) or []):
            if FreeCADOperations.fem_type(member) == "Fem::SolverCalculiX":
                return member
        raise OperationError("analysis has no CalculiX solver")

    def add_connection(
        self, analysis: str, kind: str, params: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Create a native tie or hard-contact connection.

        ``references`` always contains ``(slave, master)`` in that order;
        this is preserved for CalculiX's dependent/independent writer order.
        """

        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        if not isinstance(kind, str) or kind not in {"tie", "contact"}:
            raise OperationError("unsupported connection kind")
        if not isinstance(params, Mapping):
            raise OperationError("connection parameters must be an object")
        solver = self._analysis_solver(analysis_obj)
        analysis_type = str(getattr(solver, "AnalysisType", "")).strip().lower()
        if analysis_type != "static":
            raise OperationError("connections require a static analysis")

        raw_references = params.get("references")
        if raw_references is None:
            # Direct callers may provide the public target aliases; bridge
            # callers pass normalized references so object resolution remains
            # inside this native operation boundary.
            raw_references = [params.get("slave"), params.get("master")]
        references = self._references(doc, raw_references)
        self._validate_connection_references(references)
        name = _safe_name(params.get("name"), "Constraint" + kind.title())

        if kind == "tie":
            if "tolerance_m" not in params or params["tolerance_m"] is None:
                raise OperationError("tolerance_m is required for tie")
            if "adjust" not in params or params["adjust"] is None:
                raise OperationError("adjust is required for tie")
            tolerance_m = params["tolerance_m"]
            tolerance = self._strict_analysis_number(tolerance_m, "tolerance_m", 0.0, 1e6)
            adjust = params["adjust"]
            if not isinstance(adjust, bool):
                raise OperationError("adjust must be boolean")
            helper = "makeConstraintTie"
        else:
            if params.get("surface_behavior") != "hard":
                raise OperationError("surface_behavior is unsupported")
            if any(key in params for key in ("tolerance_m", "tolerance", "adjust")):
                raise OperationError("tie fields are unsupported for contact")
            helper = "makeConstraintContact"

        with self._transaction(doc, "Add {} connection".format(kind)):
            obj = self._connection_factory(self.objects_fem, helper, doc, name)
            self._set_connection_property(obj, "References", references)
            if kind == "tie":
                self._set_connection_property(obj, "Tolerance", tolerance * 1000.0)
                self._set_connection_property(obj, "Adjust", adjust)
                self._set_connection_property(obj, "CyclicSymmetry", False)
            else:
                self._set_connection_property(obj, "SurfaceBehavior", "Hard")
                self._set_connection_property(obj, "Friction", False)
                self._set_connection_property(obj, "EnableThermalContact", False)
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
        normalized_amplitude = self._normalize_amplitude(params.get("amplitude"))
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
            if normalized_amplitude is not None:
                self._apply_amplitude(obj, normalized_amplitude)
            self._add_to_analysis(analysis_obj, obj)
        return {"name": self._object_id(obj), "kind": "remote_load"}

    @staticmethod
    def _remote_displacement_vector(
        data: Mapping[str, Any], key: str, limit: float
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """Read an optional rigid-body displacement/rotation vector.

        A ``None`` component deliberately means Free; numeric zero is still a
        constrained component and therefore must not be collapsed to ``None``.
        """

        value = data.get(key)
        if value is None:
            return (None, None, None)
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise OperationError("{} must contain exactly three components".format(key))
        values: list[Optional[float]] = []
        for component in value:
            if component is None:
                values.append(None)
                continue
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                raise OperationError("{} must be numeric or null".format(key))
            number = float(component)
            if not math.isfinite(number) or abs(number) > limit:
                raise OperationError("{} is outside the allowed range".format(key))
            values.append(number)
        return (values[0], values[1], values[2])

    def _remote_rotation(self, values: tuple[Optional[float], Optional[float], Optional[float]]) -> Any:
        """Convert a rotation-vector (radians) to FreeCAD axis/angle form."""

        components = tuple(0.0 if value is None else value for value in values)
        magnitude = math.sqrt(sum(component * component for component in components))
        rotation_cls = getattr(self.app, "Rotation", None)
        if not callable(rotation_cls):
            # Native FreeCAD always provides App.Rotation.  The tuple fallback
            # keeps native-shaped fakes lightweight while preserving values.
            return components
        if magnitude == 0.0:
            axis = self._vector((0.0, 0.0, 1.0))
        else:
            axis = self._vector(tuple(component / magnitude for component in components))
        try:
            return rotation_cls(axis, Radian=magnitude)
        except TypeError:
            try:
                return rotation_cls(axis, magnitude)
            except Exception as exc:
                raise OperationError("FreeCAD Rotation could not be constructed") from exc
        except Exception as exc:
            raise OperationError("FreeCAD Rotation could not be constructed") from exc

    def add_remote_displacement(self, analysis: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        """Create a rigid-body kinematic condition at a global reference point."""

        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        if not isinstance(params, Mapping):
            raise OperationError("remote displacement parameters must be an object")
        normalized_amplitude = self._normalize_amplitude(params.get("amplitude"))
        references = self._references(doc, params.get("references"))
        self._validate_remote_references(references)
        reference_point_m = self._remote_vector(params, "reference_point_m", 1e9, required=True)
        translation_m = self._remote_displacement_vector(params, "translation_m", 1e9)
        rotation_rad = self._remote_displacement_vector(params, "rotation_rad", 1e6)
        if not any(component is not None for component in (*translation_m, *rotation_rad)):
            raise OperationError("translation_m or rotation_rad must constrain a component")
        name = _safe_name(params.get("name"), "RemoteDisplacement")

        with self._transaction(doc, "Add remote displacement"):
            obj = self._new_object(doc, "Fem::ConstraintRigidBody", name, "makeConstraintRigidBody")
            try:
                obj.References = references
            except Exception as exc:
                raise OperationError("remote displacement references are invalid") from exc
            obj.ReferenceNode = self._vector(tuple(component * 1000.0 for component in reference_point_m))
            displacement_mm = tuple(0.0 if component is None else component * 1000.0 for component in translation_m)
            obj.Displacement = self._vector(displacement_mm)
            obj.Rotation = self._remote_rotation(rotation_rad)
            for axis, component in zip(("X", "Y", "Z"), translation_m):
                setattr(obj, "TranslationalMode" + axis, "Constraint" if component is not None else "Free")
            for axis, component in zip(("X", "Y", "Z"), rotation_rad):
                setattr(obj, "RotationalMode" + axis, "Constraint" if component is not None else "Free")
            if normalized_amplitude is not None:
                self._apply_amplitude(obj, normalized_amplitude)
            self._add_to_analysis(analysis_obj, obj)
        return {"name": self._object_id(obj), "kind": "remote_displacement"}

    @classmethod
    def _validate_centrifugal_axis(cls, references: list[tuple[Any, str]]) -> None:
        if len(references) != 1:
            raise OperationError("centrifugal rotation axis must contain exactly one edge")
        obj, subelement = references[0]
        shape = getattr(obj, "Shape", None)
        getter = getattr(shape, "getElement", None) if shape is not None else None
        if not callable(getter):
            raise OperationError("centrifugal axis Shape cannot resolve subelements")
        shape_is_null = getattr(shape, "isNull", None)
        if callable(shape_is_null) and shape_is_null():
            raise OperationError("centrifugal axis Shape is null")
        try:
            axis = getter(subelement)
        except Exception as exc:
            raise OperationError("centrifugal axis subelement does not exist") from exc
        axis_is_null = getattr(axis, "isNull", None) if axis is not None else None
        if (
            axis is None
            or (callable(axis_is_null) and axis_is_null())
            or str(getattr(axis, "ShapeType", "")) != "Edge"
        ):
            raise OperationError("centrifugal axis must be an Edge")
        curve = getattr(axis, "Curve", None)
        curve_type = getattr(curve, "TypeId", "") if curve is not None else ""
        if str(curve_type) != "Part::GeomLine":
            raise OperationError("centrifugal axis must be a straight line")

    @classmethod
    def _validate_centrifugal_bodies(cls, references: list[tuple[Any, str]]) -> None:
        for obj, subelement in references:
            if not subelement.startswith("Solid"):
                raise OperationError("centrifugal targets must use SolidN")
            suffix = subelement[5:]
            if not suffix.isascii() or not suffix.isdigit() or int(suffix) <= 0:
                raise OperationError("centrifugal target subelement is invalid")
            shape = getattr(obj, "Shape", None)
            solids = getattr(shape, "Solids", None) if shape is not None else None
            try:
                solid = solids[int(suffix) - 1]
            except Exception as exc:
                raise OperationError("centrifugal target solid does not exist") from exc
            solid_is_null = getattr(solid, "isNull", None) if solid is not None else None
            if (
                solid is None
                or (callable(solid_is_null) and solid_is_null())
                or str(getattr(solid, "ShapeType", "")) != "Solid"
            ):
                raise OperationError("centrifugal target is not a Solid")

    def add_centrifugal_load(self, analysis: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        """Create FreeCAD's scripted centrifugal body-load object."""

        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        if not isinstance(params, Mapping):
            raise OperationError("centrifugal load parameters must be an object")
        if "amplitude" in params:
            raise OperationError("amplitude is unsupported for centrifugal loads")
        raw_references = params.get("references", [])
        references = [] if raw_references == [] else self._references(doc, raw_references)
        self._validate_centrifugal_bodies(references)
        axis_references = self._references(doc, params.get("rotation_axis"))
        self._validate_centrifugal_axis(axis_references)
        raw_frequency = params.get("rotation_frequency_hz")
        if isinstance(raw_frequency, bool) or not isinstance(raw_frequency, (int, float)):
            raise OperationError("rotation_frequency_hz must be numeric")
        frequency = _finite_number(raw_frequency, "rotation_frequency_hz")
        if frequency <= 0.0 or frequency > 1e9:
            raise OperationError("rotation_frequency_hz is outside the allowed range")
        name = _safe_name(params.get("name"), "CentrifugalLoad")

        with self._transaction(doc, "Add centrifugal load"):
            obj = self._new_object(doc, "Fem::ConstraintPython", name, "makeConstraintCentrif")
            try:
                obj.References = references
                obj.RotationAxis = axis_references
                obj.RotationFrequency = self._unit_value(
                    frequency, "Hz", "rotation_frequency_hz"
                )
            except Exception as exc:
                raise OperationError("centrifugal native properties are unavailable") from exc
            self._add_to_analysis(analysis_obj, obj)
        return {"name": self._object_id(obj), "kind": "centrifugal"}

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

    @staticmethod
    def _material_has_density(obj: Any) -> bool:
        """Return whether a native material object contains a finite density."""

        values: list[Any] = []
        material = getattr(obj, "Material", None)
        if isinstance(material, Mapping):
            for key, value in material.items():
                if "density" in str(key).lower():
                    values.append(value)
        for key in ("Density", "density", "DensityValue", "density_kg_m3"):
            try:
                if hasattr(obj, key):
                    values.append(getattr(obj, key))
            except Exception:
                pass
        for value in values:
            if isinstance(value, bool) or value is None:
                continue
            try:
                # FreeCAD quantity strings start with the numeric magnitude
                # (for example ``7850 kg/m^3``); plain numbers are accepted as
                # well.  Do not require a particular unit spelling here.
                number = float(str(value).strip().split()[0])
            except (TypeError, ValueError, IndexError):
                continue
            if math.isfinite(number) and number >= 0.0:
                return True
        return False

    @classmethod
    def _buckling_member_diagnostics(cls, members: list[Any]) -> list[str]:
        """Require at least one support and one load for a buckling solve."""

        has_support = False
        has_load = False
        for item in members:
            type_id = str(getattr(item, "TypeId", ""))
            semantic = cls.fem_type(item)
            token = (semantic + " " + type_id).lower()
            if "solvercalculix" in token or "femmesh" in token:
                continue
            is_rigid = "rigidbody" in token or "rigid_body" in token
            if any(
                marker in token
                for marker in ("constraintfixed", "constraintdisplacement", "constraintcontact", "support")
            ):
                has_support = True
            if is_rigid:
                mode_values = " ".join(
                    str(getattr(item, name, "")).lower()
                    for name in (
                        "TranslationalModeX", "TranslationalModeY", "TranslationalModeZ",
                        "RotationalModeX", "RotationalModeY", "RotationalModeZ",
                    )
                )
                if "load" in mode_values or not mode_values.strip():
                    has_load = True
                else:
                    has_support = True
            elif any(
                marker in token
                for marker in (
                    "constraintforce", "constraintpressure", "constraintselfweight",
                    "constraintcentrif", "constraintacceleration", "constraintload",
                    "remoteload", "force", "pressure", "selfweight", "centrifugal",
                )
            ):
                has_load = True
        diagnostics = []
        if not has_support:
            diagnostics.append("buckling analysis has no support constraint")
        if not has_load:
            diagnostics.append("buckling analysis has no load")
        return diagnostics

    @staticmethod
    def _check_diagnostics(checked: Any, strict: bool) -> list[Any]:
        """Normalize FreeCAD checker output without treating messages as success."""

        if isinstance(checked, tuple) and len(checked) == 2 and isinstance(checked[0], bool):
            ok, message = checked
            if not ok:
                return [message] if message else ["FreeCAD analysis check failed"]
            # Some FreeCAD versions return ``(True, message)`` for a warning.
            # Strict validation must surface that message rather than silently
            # considering the check successful.
            if strict and message:
                return [message]
            return []
        if isinstance(checked, bool):
            return [] if checked else ["FreeCAD analysis check failed"]
        if checked is None or checked == "":
            return []
        if isinstance(checked, (list, tuple)):
            return list(checked)
        return [checked]

    def validate(self, analysis: str, strict: bool = True) -> Dict[str, Any]:
        doc = self._document()
        analysis_obj = self._find(doc, analysis)
        members = list(getattr(analysis_obj, "Group", []) or [])
        solver = next((item for item in members if self.fem_type(item) == "Fem::SolverCalculiX"), None)
        mesh = next((item for item in members if "FemMesh" in getattr(item, "TypeId", "")), None)
        diagnostics: list[Any] = []
        if not isinstance(strict, bool):
            raise OperationError("strict must be boolean")
        if solver is None:
            diagnostics.append("analysis has no CalculiX solver")
        if mesh is None:
            diagnostics.append("analysis has no mesh")
        if solver is not None and mesh is not None and _checksanalysis is not None and _membertools is not None:
            try:
                member = _membertools.AnalysisMember(analysis_obj)
                checked = _checksanalysis.check_member_for_solver_calculix(analysis_obj, solver, mesh, member)
                diagnostics.extend(self._check_diagnostics(checked, strict))
            except Exception as exc:
                diagnostics.append(str(exc))
        else:
            kinds = {str(getattr(item, "TypeId", "")) for item in members}
            if not any("Material" in kind for kind in kinds):
                diagnostics.append("analysis has no material")
            if not any("Constraint" in kind for kind in kinds):
                diagnostics.append("analysis has no constraints")

        analysis_type = (
            str(getattr(solver, "AnalysisType", "static")).strip().lower()
            if solver is not None
            else "static"
        )
        if analysis_type == "frequency":
            material_members = [
                item
                for item in members
                if "material" in (self.fem_type(item) + " " + str(getattr(item, "TypeId", ""))).lower()
            ]
            if not material_members or not any(self._material_has_density(item) for item in material_members):
                diagnostics.append("frequency analysis requires material density")
        elif analysis_type == "buckling":
            diagnostics.extend(self._buckling_member_diagnostics(members))
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
