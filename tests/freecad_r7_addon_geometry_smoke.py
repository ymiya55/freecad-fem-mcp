"""FreeCAD 1.1.3 smoke for the R7.1 native Addon geometry route.

Run this portable script with the installed FreeCAD command-line host.  It
creates only native CalculiX analyses and FEM objects, then verifies the
property/type mappings used by :class:`FreeCADOperations`.  No host-specific
executable path is embedded in the source or JSON summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _value(value: Any, unit: str | None = None) -> float:
    if unit is not None and hasattr(value, "getValueAs"):
        value = value.getValueAs(unit)
    if hasattr(value, "Value"):
        value = value.Value
    return float(value)


def _property(obj: Any, name: str, type_id: str) -> Any:
    _assert(name in getattr(obj, "PropertiesList", []), "{} missing {}".format(obj.Name, name))
    actual = obj.getTypeIdOfProperty(name)
    _assert(actual == type_id, "{}.{} type {} != {}".format(obj.Name, name, actual, type_id))
    return getattr(obj, name)


def _geometry(doc: Any, name: str, shape: Any) -> Any:
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    return obj


def _new_document(app: Any, name: str) -> Any:
    return app.newDocument(name)


def _close_document(app: Any, doc: Any) -> None:
    app.closeDocument(getattr(doc, "Name", ""))


def main() -> dict[str, Any]:
    script_path = Path(globals().get("__file__", "tests/freecad_r7_addon_geometry_smoke.py"))
    root = script_path.resolve().parents[1]
    addon = root / "addon"
    if str(addon) not in sys.path:
        sys.path.insert(0, str(addon))

    import FreeCAD as app  # type: ignore
    import ObjectsFem  # type: ignore
    import Part  # type: ignore

    from FreeCADFEMMCP.operations import FreeCADOperations  # type: ignore

    operations = FreeCADOperations(app=app, objects_fem=ObjectsFem)
    summary: dict[str, Any] = {"analyses": [], "sections": []}

    shell_doc = _new_document(app, "R71ShellSmoke")
    try:
        shell_result = operations.create_analysis("ShellAnalysis")
        shell_surface = _geometry(shell_doc, "ShellSurface", Part.makePlane(100, 100))
        mesh_result = operations.create_mesh(
            "ShellAnalysis", "ShellMesh2D", element_dimension="2d", shape=shell_surface.Name
        )
        mesh = shell_doc.getObject(mesh_result["name"])
        _property(mesh, "ElementDimension", "App::PropertyEnumeration")
        _assert(mesh.ElementDimension == "2D", "mesh dimension was not mapped to native 2D")
        shell_result = operations.assign_element_geometry(
            "ShellAnalysis",
            "shell",
            {
                "name": "ShellGeometry",
                "references": [{"object": shell_surface.Name, "sub_element": "Face1"}],
                "thickness_m": 0.002,
                "offset": -0.25,
            },
        )
        shell = shell_doc.getObject(shell_result["name"])
        _assert(shell.TypeId == "Fem::FeaturePython", shell.TypeId)
        _assert(getattr(shell.Proxy, "Type", None) == "Fem::ElementGeometry2D", "shell proxy type")
        _property(shell, "References", "App::PropertyLinkSubListGlobal")
        _assert(_value(_property(shell, "Thickness", "App::PropertyLength"), "m") == 0.002, "shell thickness")
        _assert(_value(_property(shell, "Offset", "App::PropertyFloat")) == -0.25, "shell offset")
        summary["analyses"].append(shell_result["name"])
        summary["mesh_dimension"] = mesh.ElementDimension
    finally:
        _close_document(app, shell_doc)

    beam_doc = _new_document(app, "R71BeamSmoke")
    try:
        beam_result = operations.create_analysis("BeamAnalysis")
        line = _geometry(beam_doc, "BeamLine", Part.makeLine(app.Vector(0, 0, 0), app.Vector(100, 0, 0)))
        sections = (
            ("rectangular", {"rect_width_m": 0.01, "rect_height_m": 0.02}, "Rectangular"),
            ("circular", {"circ_diameter_m": 0.02}, "Circular"),
            ("pipe", {"pipe_diameter_m": 0.03, "pipe_thickness_m": 0.002}, "Pipe"),
            ("elliptical", {"axis1_length_m": 0.03, "axis2_length_m": 0.02}, "Elliptical"),
            (
                "box",
                {
                    "box_width_m": 0.03,
                    "box_height_m": 0.04,
                    "box_t1_m": 0.002,
                    "box_t2_m": 0.002,
                    "box_t3_m": 0.002,
                    "box_t4_m": 0.002,
                },
                "Box",
            ),
        )
        for index, (section_type, values, native_section) in enumerate(sections, start=1):
            result = operations.assign_element_geometry(
                "BeamAnalysis",
                "beam_section",
                {
                    "name": "BeamSection{}".format(index),
                    "references": [{"object": line.Name, "sub_element": "Edge1"}],
                    "section_type": section_type,
                    **values,
                },
            )
            obj = beam_doc.getObject(result["name"])
            _assert(getattr(obj.Proxy, "Type", None) == "Fem::ElementGeometry1D", "beam proxy type")
            _assert(_property(obj, "References", "App::PropertyLinkSubListGlobal"), "beam references")
            _assert(_property(obj, "SectionType", "App::PropertyEnumeration") == native_section, "beam section enum")
            summary["sections"].append(native_section)
        solver = beam_doc.getObject(beam_result["solver"])
        _assert(_property(solver, "BeamReducedIntegration", "App::PropertyBool") is True, "pipe reduced integration")
        rotation_result = operations.assign_element_geometry(
            "BeamAnalysis",
            "beam_rotation",
            {
                "name": "BeamRotation",
                "references": [{"object": line.Name, "sub_element": "Edge1"}],
                "rotation_rad": 0.25,
            },
        )
        rotation = beam_doc.getObject(rotation_result["name"])
        _assert(getattr(rotation.Proxy, "Type", None) == "Fem::ElementRotation1D", "rotation proxy type")
        _assert(_value(_property(rotation, "Rotation", "App::PropertyAngle"), "rad") == 0.25, "rotation")
        summary["analyses"].append(beam_result["name"])
    finally:
        _close_document(app, beam_doc)

    truss_doc = _new_document(app, "R71TrussSmoke")
    try:
        truss_result = operations.create_analysis("TrussAnalysis")
        line = _geometry(truss_doc, "TrussLine", Part.makeLine(app.Vector(0, 0, 0), app.Vector(100, 0, 0)))
        truss_geometry = operations.assign_element_geometry(
            "TrussAnalysis",
            "beam_section",
            {
                "name": "TrussSection",
                "references": [{"object": line.Name, "sub_element": "Edge1"}],
                "section_type": "truss",
                "truss_area_m2": 0.0002,
            },
        )
        truss = truss_doc.getObject(truss_geometry["name"])
        _assert(_property(truss, "SectionType", "App::PropertyEnumeration") == "Rectangular", "truss enum")
        _assert(_value(_property(truss, "TrussArea", "App::PropertyArea"), "m^2") == 0.0002, "truss area")
        solver = truss_doc.getObject(truss_result["solver"])
        _assert(_property(solver, "ExcludeBendingStiffness", "App::PropertyBool") is True, "truss exclusion")
        summary["analyses"].append(truss_result["name"])
    finally:
        _close_document(app, truss_doc)

    return {"ok": True, **summary}


def run() -> None:
    try:
        import FreeCAD as app  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this smoke with FreeCADCmd 1.1.3") from exc
    if getattr(app, "_R71AddonGeometrySmokeRunning", False):
        return
    app._R71AddonGeometrySmokeRunning = True
    print(json.dumps(main(), separators=(",", ":"), sort_keys=True))


# FreeCADCmd executes positional scripts under a filename-derived module name,
# so this executable intentionally calls run() unconditionally.
run()
