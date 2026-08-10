"""Portable FreeCAD 1.1.3 smoke for R7.4 material regions and transforms.

Run with the FreeCAD command-line interpreter.  The script exercises only the
public Addon operations and the native CalculiX transform writer; no legacy
solver, custom INP, or machine-specific path is used.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _references(obj: Any) -> list[tuple[str, list[str]]]:
    values = []
    for item in getattr(obj, "References", []) or []:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        target, subelements = item
        if isinstance(subelements, str):
            subelements = [subelements]
        values.append((str(getattr(target, "Name", "")), list(subelements or [])))
    return values


def _beam_references(name: str, edge: str) -> list[dict[str, Any]]:
    return [{"object": name, "sub_element": edge}]


def _shell_references(name: str, face: str) -> list[dict[str, Any]]:
    return [{"object": name, "sub_element": face}]


def _beam_probe(app: Any, objects_fem: Any, operations: Any) -> dict[str, Any]:
    import Part  # type: ignore

    doc = app.newDocument("R7BeamMaterialTransform")
    try:
        beam = doc.addObject("Part::Feature", "BeamRegion")
        beam.Shape = Part.makeCompound(
            [
                Part.makeLine(app.Vector(0, 0, 0), app.Vector(10, 0, 0)),
                Part.makeLine(app.Vector(0, 1, 0), app.Vector(10, 1, 0)),
            ]
        )
        analysis = operations.create_analysis("BeamAnalysis", "static")
        operations.assign_element_geometry(
            analysis["name"],
            "beam_section",
            {
                "references": _beam_references("BeamRegion", "Edge1"),
                "section_type": "rectangular",
                "rect_width_m": 0.01,
                "rect_height_m": 0.02,
            },
        )
        operations.assign_element_geometry(
            analysis["name"],
            "beam_section",
            {
                "references": _beam_references("BeamRegion", "Edge2"),
                "section_type": "circular",
                "circ_diameter_m": 0.02,
            },
        )
        operations.set_material(
            analysis["name"],
            {"name": "BeamMaterialA", "targets": [{"object_name": "BeamRegion", "subelements": ["Edge1"]}]},
        )
        operations.set_material(
            analysis["name"],
            {"name": "BeamMaterialB", "targets": [{"object_name": "BeamRegion", "subelements": ["Edge2"]}]},
        )
        transform = operations.add_constraint(
            analysis["name"],
            "transform",
            {
                "references": _beam_references("BeamRegion", "Edge1"),
                "transform_type": "rectangular",
                "rotation_rad": [0.0, 0.0, 0.5],
            },
        )
        native_transform = doc.getObject(transform["name"])
        _assert(native_transform.TransformType == "Rectangular", "beam transform enum")
        _assert(_references(native_transform) == [("BeamRegion", ["Edge1"])], "beam transform references")
        writer = __import__("femsolver.calculix.write_constraint_transform", fromlist=["write_constraint_transform"])
        stream = io.StringIO()
        writer.write_meshdata_constraint(stream, {"Nodes": [1]}, native_transform, None)
        writer.write_constraint(stream, {"Nodes": [1]}, native_transform, None)
        output = stream.getvalue()
        _assert("*TRANSFORM" in output and "TYPE=R" in output, "beam transform writer")
        materials = [
            doc.getObject("BeamMaterialA"),
            doc.getObject("BeamMaterialB"),
        ]
        _assert(all(_references(material) for material in materials), "beam material references")
        return {
            "materials": [_references(material) for material in materials],
            "transform": {"type": native_transform.TransformType, "writer": output},
        }
    finally:
        app.closeDocument(doc.Name)


def _shell_probe(app: Any, operations: Any) -> dict[str, Any]:
    import Part  # type: ignore

    doc = app.newDocument("R7ShellMaterialTransform")
    try:
        shell = doc.addObject("Part::Feature", "ShellRegion")
        first = Part.makePlane(10, 5, app.Vector(0, 0, 0))
        second = Part.makePlane(10, 5, app.Vector(0, 6, 0))
        shell.Shape = Part.makeCompound([first, second])
        analysis = operations.create_analysis("ShellAnalysis", "static")
        operations.assign_element_geometry(
            analysis["name"],
            "shell",
            {"references": _shell_references("ShellRegion", "Face1"), "thickness_m": 0.001},
        )
        operations.assign_element_geometry(
            analysis["name"],
            "shell",
            {"references": _shell_references("ShellRegion", "Face2"), "thickness_m": 0.001},
        )
        operations.set_material(
            analysis["name"],
            {"name": "ShellMaterialA", "targets": [{"object_name": "ShellRegion", "subelements": ["Face1"]}]},
        )
        operations.set_material(
            analysis["name"],
            {"name": "ShellMaterialB", "targets": [{"object_name": "ShellRegion", "subelements": ["Face2"]}]},
        )
        transform = operations.add_constraint(
            analysis["name"],
            "transform",
            {
                "references": _shell_references("ShellRegion", "Face1"),
                "transform_type": "cylindrical",
                "base_point_m": [0.0, 0.0, 0.0],
                "axis_m": [0.0, 0.0, 1.0],
            },
        )
        native_transform = doc.getObject(transform["name"])
        _assert(native_transform.TransformType == "Cylindrical", "shell transform enum")
        _assert(_references(native_transform) == [("ShellRegion", ["Face1"])], "shell transform references")
        writer = __import__("femsolver.calculix.write_constraint_transform", fromlist=["write_constraint_transform"])
        stream = io.StringIO()
        writer.write_meshdata_constraint(stream, {"Nodes": [1]}, native_transform, None)
        writer.write_constraint(stream, {"Nodes": [1]}, native_transform, None)
        output = stream.getvalue()
        _assert("*TRANSFORM" in output and "TYPE=C" in output, "shell transform writer")
        materials = [
            doc.getObject("ShellMaterialA"),
            doc.getObject("ShellMaterialB"),
        ]
        _assert(all(_references(material) for material in materials), "shell material references")
        return {
            "materials": [_references(material) for material in materials],
            "transform": {"type": native_transform.TransformType, "writer": output},
        }
    finally:
        app.closeDocument(doc.Name)


def run() -> None:
    try:
        import FreeCAD as app  # type: ignore
        import ObjectsFem  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this smoke with FreeCADCmd 1.1.3") from exc
    if getattr(app, "_R7MaterialTransformSmokeRunning", False):
        return
    app._R7MaterialTransformSmokeRunning = True
    addon = Path(__file__).resolve().parents[1] / "addon"
    sys.path.insert(0, str(addon))
    from FreeCADFEMMCP.operations import FreeCADOperations  # type: ignore

    operations = FreeCADOperations(app=app, objects_fem=ObjectsFem)
    result = {
        "beam": _beam_probe(app, ObjectsFem, operations),
        "shell": _shell_probe(app, operations),
    }
    print(json.dumps(result, sort_keys=True))


run()
