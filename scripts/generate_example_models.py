"""Generate geometry-only FCStd and STEP assets for the analyst examples.

Run this script with FreeCADCmd 1.1.x from the repository root::

    FreeCADCmd.exe scripts/generate_example_models.py

The generator writes only to ``examples/models``. Existing assets are preserved
unless ``--overwrite`` is supplied. Analyses, meshes, materials, constraints,
and loads are intentionally left for the MCP workflow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable


def _workspace() -> Path:
    script = Path(
        globals().get(
            "__file__", Path.cwd() / "scripts" / "generate_example_models.py"
        )
    ).resolve()
    return script.parents[1]


def _property(obj: Any, name: str, value: str) -> None:
    if name not in list(getattr(obj, "PropertiesList", []) or []):
        obj.addProperty("App::PropertyString", name, "Example geometry")
    setattr(obj, name, value)


def _subelement_near(shape: Any, kind: str, axis: str, value: float) -> str:
    collection = list(getattr(shape, kind + "s", []) or [])
    if not collection:
        raise RuntimeError("shape has no {}s".format(kind.lower()))
    index, _ = min(
        enumerate(collection, 1),
        key=lambda item: abs(float(getattr(item[1].CenterOfMass, axis)) - value),
    )
    return "{}{}".format(kind, index)


def _contact_face(shape: Any, z_value: float, normal_z: float) -> str:
    candidates: list[tuple[float, int]] = []
    for index, face in enumerate(list(shape.Faces), 1):
        if abs(float(face.CenterOfMass.z) - z_value) > 1.0e-7:
            continue
        try:
            normal = face.normalAt(0.0, 0.0)
            score = abs(float(normal.z) - normal_z)
        except Exception:
            score = 10.0
        candidates.append((score, index))
    if not candidates:
        raise RuntimeError("contact face was not found")
    return "Face{}".format(min(candidates)[1])


def _add_geometry(doc: Any, name: str, label: str, shape: Any) -> Any:
    obj = doc.addObject("Part::Feature", name)
    obj.Label = label
    obj.Shape = shape
    if obj.Shape.isNull():
        raise RuntimeError("{} geometry is null".format(name))
    return obj


def _cantilever_solid(app: Any, part: Any, doc: Any) -> list[Any]:
    obj = _add_geometry(
        doc,
        "CantileverSolid",
        "Cantilever solid, 200 x 20 x 4 mm",
        part.makeBox(200.0, 20.0, 4.0),
    )
    _property(obj, "SupportSubelement", _subelement_near(obj.Shape, "Face", "x", 0.0))
    _property(obj, "LoadSubelement", _subelement_near(obj.Shape, "Face", "x", 200.0))
    _property(obj, "LoadReferencePointM", "[0.200, 0.010, 0.002]")
    return [obj]


def _cantilever_shell(app: Any, part: Any, doc: Any) -> list[Any]:
    obj = _add_geometry(
        doc,
        "CantileverShell",
        "Cantilever shell midsurface, 200 x 20 mm",
        part.makePlane(200.0, 20.0, app.Vector(0.0, 0.0, 0.0)),
    )
    _property(obj, "ShellSubelement", "Face1")
    _property(obj, "SupportSubelement", _subelement_near(obj.Shape, "Edge", "x", 0.0))
    _property(obj, "LoadSubelement", _subelement_near(obj.Shape, "Edge", "x", 200.0))
    _property(obj, "LoadReferencePointM", "[0.200, 0.010, 0.000]")
    _property(obj, "ShellThicknessM", "0.004")
    return [obj]


def _cantilever_beam(app: Any, part: Any, doc: Any) -> list[Any]:
    obj = _add_geometry(
        doc,
        "CantileverBeam",
        "Cantilever beam centerline, 200 mm",
        part.makeLine(app.Vector(0.0, 0.0, 0.0), app.Vector(200.0, 0.0, 0.0)),
    )
    _property(obj, "BeamSubelement", "Edge1")
    _property(obj, "SupportSubelement", "Vertex1")
    _property(obj, "LoadSubelement", "Vertex2")
    _property(obj, "LoadReferencePointM", "[0.200, 0.000, 0.000]")
    _property(obj, "RectangularSectionM", "width=0.020, height=0.004")
    return [obj]


def _large_deformation(app: Any, part: Any, doc: Any) -> list[Any]:
    obj = _add_geometry(
        doc,
        "LargeDeformationCantilever",
        "Large-deformation cantilever, 1000 x 20 x 10 mm",
        part.makeBox(1000.0, 20.0, 10.0),
    )
    _property(obj, "SupportSubelement", _subelement_near(obj.Shape, "Face", "x", 0.0))
    _property(obj, "LoadSubelement", _subelement_near(obj.Shape, "Face", "x", 1000.0))
    _property(obj, "LoadReferencePointM", "[1.000, 0.010, 0.005]")
    return [obj]


def _contact(app: Any, part: Any, doc: Any) -> list[Any]:
    lower = part.makeBox(20.0, 20.0, 10.0, app.Vector(0.0, 0.0, 0.0))
    upper = part.makeBox(20.0, 20.0, 10.0, app.Vector(0.0, 0.0, 10.0))
    obj = _add_geometry(
        doc,
        "ContactPair",
        "Two-block contact pair, 20 x 20 x 10 mm each",
        part.makeCompound([lower, upper]),
    )
    if len(list(obj.Shape.Solids)) != 2:
        raise RuntimeError("contact compound must contain two solids")
    _property(obj, "SupportSubelement", _subelement_near(obj.Shape, "Face", "z", 0.0))
    _property(obj, "LoadSubelement", _subelement_near(obj.Shape, "Face", "z", 20.0))
    _property(obj, "MasterSubelement", _contact_face(obj.Shape, 10.0, 1.0))
    _property(obj, "SlaveSubelement", _contact_face(obj.Shape, 10.0, -1.0))
    _property(obj, "LoadReferencePointM", "[0.010, 0.010, 0.020]")
    return [obj]


def _modal(app: Any, part: Any, doc: Any) -> list[Any]:
    obj = _add_geometry(
        doc,
        "ModalCantilever",
        "Modal cantilever, 100 x 10 x 10 mm",
        part.makeBox(100.0, 10.0, 10.0),
    )
    _property(obj, "SupportSubelement", _subelement_near(obj.Shape, "Face", "x", 0.0))
    return [obj]


def _buckling(app: Any, part: Any, doc: Any) -> list[Any]:
    obj = _add_geometry(
        doc,
        "BucklingColumn",
        "Fixed-free buckling column, 100 x 10 x 10 mm",
        part.makeBox(100.0, 10.0, 10.0),
    )
    _property(obj, "SupportSubelement", _subelement_near(obj.Shape, "Face", "x", 0.0))
    _property(obj, "LoadSubelement", _subelement_near(obj.Shape, "Face", "x", 100.0))
    return [obj]


def _counts(objects: list[Any]) -> dict[str, int]:
    return {
        "objects": len(objects),
        "solids": sum(len(list(obj.Shape.Solids)) for obj in objects),
        "faces": sum(len(list(obj.Shape.Faces)) for obj in objects),
        "edges": sum(len(list(obj.Shape.Edges)) for obj in objects),
        "vertices": sum(len(list(obj.Shape.Vertexes)) for obj in objects),
    }


def _verify_step(app: Any, importer: Any, path: Path, expected: dict[str, int]) -> dict[str, int]:
    """Re-import one STEP file and verify its topological dimension."""

    document = app.newDocument("Verify_" + path.stem.replace("-", "_"))
    try:
        importer.insert(str(path), document.Name)
        document.recompute()
        objects = [
            obj
            for obj in list(document.Objects)
            if hasattr(obj, "Shape") and not obj.Shape.isNull()
        ]
        actual = _counts(objects)
        for key in ("solids", "faces", "edges", "vertices"):
            if expected[key] > 0 and actual[key] < expected[key]:
                raise RuntimeError(
                    "{} lost {} topology during STEP round trip: {} < {}".format(
                        path.name, key, actual[key], expected[key]
                    )
                )
        return actual
    finally:
        app.closeDocument(document.Name)


def _normalize_step_text(path: Path) -> None:
    """Remove exporter-added trailing spaces while preserving STEP content."""

    text = path.read_text(encoding="utf-8")
    normalized = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
    path.write_text(normalized, encoding="utf-8", newline="\n")


def run() -> dict[str, Any]:
    try:
        import FreeCAD as app  # type: ignore
        import Import  # type: ignore
        import Part  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this generator with FreeCADCmd 1.1.x") from exc

    if getattr(app, "_ExampleModelsRunning", False):
        return {"ok": True, "reentered": True}
    app._ExampleModelsRunning = True
    try:
        workspace = _workspace()
        output = (workspace / "examples" / "models").resolve()
        output.relative_to(workspace)
        output.mkdir(parents=True, exist_ok=True)
        overwrite = "--overwrite" in list(sys.argv[1:])
        definitions: list[tuple[str, Callable[[Any, Any, Any], list[Any]]]] = [
            ("cantilever-solid", _cantilever_solid),
            ("cantilever-shell", _cantilever_shell),
            ("cantilever-beam", _cantilever_beam),
            ("large-deformation", _large_deformation),
            ("contact", _contact),
            ("modal", _modal),
            ("linear-buckling", _buckling),
        ]
        expected = [output / (name + suffix) for name, _ in definitions for suffix in (".FCStd", ".step")]
        existing = [path for path in expected if path.exists()]
        if existing and not overwrite:
            raise SystemExit(
                "refusing to overwrite generated assets; rerun with --overwrite: {}".format(
                    ", ".join(path.name for path in existing)
                )
            )
        if overwrite:
            # Remove only the fixed, workspace-local outputs enumerated above.
            # FreeCAD otherwise creates timestamped FCBak files during saveAs.
            for path in existing:
                path.unlink()

        report: dict[str, Any] = {"ok": True, "models": {}}
        for stem, builder in definitions:
            document = app.newDocument("Example_" + stem.replace("-", "_"))
            try:
                objects = builder(app, Part, document)
                document.recompute()
                fcstd = output / (stem + ".FCStd")
                step = output / (stem + ".step")
                document.saveAs(str(fcstd))
                Import.export(objects, str(step))
                _normalize_step_text(step)
                if not fcstd.is_file() or fcstd.stat().st_size < 100:
                    raise RuntimeError("invalid FCStd output: {}".format(fcstd.name))
                if not step.is_file() or step.stat().st_size < 100:
                    raise RuntimeError("invalid STEP output: {}".format(step.name))
                geometry = _counts(objects)
                step_geometry = _verify_step(app, Import, step, geometry)
                report["models"][stem] = {
                    "fcstd": fcstd.relative_to(workspace).as_posix(),
                    "step": step.relative_to(workspace).as_posix(),
                    "geometry": geometry,
                    "step_geometry": step_geometry,
                }
            finally:
                app.closeDocument(document.Name)
        print(json.dumps(report, separators=(",", ":"), sort_keys=True))
        return report
    finally:
        app._ExampleModelsRunning = False


run()
