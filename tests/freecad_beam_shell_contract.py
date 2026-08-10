"""FreeCAD 1.1.3 native beam/shell contract probe.

Run this executable probe with the FreeCAD command-line host, for example::

    FreeCADCmd.exe tests/freecad_beam_shell_contract.py

The probe deliberately exercises only native ``ObjectsFem`` factories and the
native CalculiX geometry writer.  It does not import the MCP addon, run a
legacy solver, or inject an input deck.  Its output is a short JSON summary so
that a host-specific absolute executable path never becomes part of a report.
"""

from __future__ import annotations

import io
import json
from typing import Any


SECTION_TYPES = ["Rectangular", "Circular", "Pipe", "Elliptical", "Box"]
ELEMENT_DIMENSIONS = ["From Shape", "1D", "2D", "3D"]


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _value(value: Any, unit: str | None = None) -> float:
    if unit is not None and hasattr(value, "getValueAs"):
        value = value.getValueAs(unit)
    if hasattr(value, "Value"):
        value = value.Value
    return float(value)


def _assert_property(obj: Any, name: str, type_id: str, value: Any = None) -> None:
    _assert(name in obj.PropertiesList, f"{obj.Name} missing property {name}")
    actual = obj.getTypeIdOfProperty(name)
    _assert(actual == type_id, f"{obj.Name}.{name}: {actual!r} != {type_id!r}")
    if value is not None:
        actual_value = getattr(obj, name)
        if isinstance(value, float):
            actual_value = _value(actual_value)
        _assert(actual_value == value, f"{obj.Name}.{name}: {actual_value!r} != {value!r}")


def _check_factories(app: Any, objects_fem: Any) -> dict[str, Any]:
    import Part

    doc = app.newDocument("R7NativeContract")
    try:
        mesh = objects_fem.makeMeshGmsh(doc, "Mesh")
        _assert(mesh.TypeId == "Fem::FemMeshShapeBaseObjectPython", mesh.TypeId)
        _assert(getattr(mesh.Proxy, "Type", None) == "Fem::FemMeshGmsh", "mesh proxy type changed")
        _assert_property(mesh, "ElementDimension", "App::PropertyEnumeration")
        _assert(mesh.getEnumerationsOfProperty("ElementDimension") == ELEMENT_DIMENSIONS, "ElementDimension enum changed")
        _assert(mesh.ElementDimension == "From Shape", mesh.ElementDimension)

        geometries = {}
        for section_type in SECTION_TYPES:
            geometry = objects_fem.makeElementGeometry1D(
                doc, sectiontype=section_type, name=f"Beam{section_type}"
            )
            geometries[section_type] = geometry
            _assert(geometry.TypeId == "Fem::FeaturePython", geometry.TypeId)
            _assert(getattr(geometry.Proxy, "Type", None) == "Fem::ElementGeometry1D", "beam proxy type changed")
            _assert(type(geometry.Proxy).__module__ == "femobjects.element_geometry1D", type(geometry.Proxy))
            _assert_property(geometry, "References", "App::PropertyLinkSubListGlobal")
            _assert_property(geometry, "SectionType", "App::PropertyEnumeration")
            _assert(geometry.getEnumerationsOfProperty("SectionType") == SECTION_TYPES, "SectionType enum changed")
            _assert(geometry.SectionType == section_type, geometry.SectionType)
        rect = geometries["Rectangular"]
        line = doc.addObject("Part::Feature", "ReferenceLine")
        line.Shape = Part.makeLine(app.Vector(0, 0, 0), app.Vector(100, 0, 0))
        rect.References = [(line, "Edge1")]
        _assert(rect.References == [(line, ("Edge1",))], rect.References)
        for name, expected in {
            "RectWidth": 10.0,
            "RectHeight": 25.0,
            "CircDiameter": 25.0,
            "PipeDiameter": 25.0,
            "PipeThickness": 2.0,
            "Axis1Length": 10.0,
            "Axis2Length": 25.0,
            "BoxHeight": 25.0,
            "BoxWidth": 10.0,
            "BoxT1": 2.0,
            "BoxT2": 2.0,
            "BoxT3": 2.0,
            "BoxT4": 2.0,
            "TrussArea": 10.0,
        }.items():
            expected_type = "App::PropertyArea" if name == "TrussArea" else "App::PropertyLength"
            _assert_property(rect, name, expected_type)
            unit = "mm^2" if name == "TrussArea" else "mm"
            _assert(_value(getattr(rect, name), unit) == expected, f"{name} default changed")

        rotation = objects_fem.makeElementRotation1D(doc, "BeamRotation")
        _assert(rotation.TypeId == "Fem::FeaturePython", rotation.TypeId)
        _assert(getattr(rotation.Proxy, "Type", None) == "Fem::ElementRotation1D", "rotation proxy type changed")
        _assert(type(rotation.Proxy).__module__ == "femobjects.element_rotation1D", type(rotation.Proxy))
        _assert_property(rotation, "References", "App::PropertyLinkSubListGlobal")
        _assert_property(rotation, "Rotation", "App::PropertyAngle")
        _assert(_value(rotation.Rotation, "deg") == 0.0, rotation.Rotation)
        rotation.References = [(line, ["Edge1"])]
        _assert(rotation.References == [(line, ("Edge1",))], rotation.References)

        shell = objects_fem.makeElementGeometry2D(doc, thickness=3.5, name="ShellGeometry")
        _assert(shell.TypeId == "Fem::FeaturePython", shell.TypeId)
        _assert(getattr(shell.Proxy, "Type", None) == "Fem::ElementGeometry2D", "shell proxy type changed")
        _assert(type(shell.Proxy).__module__ == "femobjects.element_geometry2D", type(shell.Proxy))
        _assert_property(shell, "References", "App::PropertyLinkSubListGlobal")
        _assert_property(shell, "Thickness", "App::PropertyLength")
        _assert_property(shell, "Offset", "App::PropertyFloat")
        _assert(_value(shell.Thickness, "mm") == 3.5, shell.Thickness)
        _assert(_value(shell.Offset) == 0.0, shell.Offset)
        surface = doc.addObject("Part::Feature", "ReferenceSurface")
        surface.Shape = Part.makePlane(100, 100)
        shell.References = [(surface, "Face1")]
        _assert(shell.References == [(surface, ("Face1",))], shell.References)

        solver = objects_fem.makeSolverCalculiX(doc, "Solver")
        _assert(getattr(solver.Proxy, "Type", None) == "Fem::SolverCalculiX", "solver proxy type changed")
        _assert(type(solver.Proxy).__module__ == "femobjects.solver_calculix", type(solver.Proxy))
        for name, expected in {
            "BeamReducedIntegration": True,
            "BeamShellResultOutput3D": True,
            "ExcludeBendingStiffness": False,
        }.items():
            _assert_property(solver, name, "App::PropertyBool", expected)

        return {
            "mesh_type": mesh.TypeId,
            "mesh_element_dimension": mesh.getEnumerationsOfProperty("ElementDimension"),
            "beam_type": rect.TypeId,
            "beam_proxy": f"{type(rect.Proxy).__module__}.{type(rect.Proxy).__name__}",
            "beam_section_types": rect.getEnumerationsOfProperty("SectionType"),
            "beam_references_type": rect.getTypeIdOfProperty("References"),
            "rotation_type": rotation.TypeId,
            "rotation_references_type": rotation.getTypeIdOfProperty("References"),
            "shell_type": shell.TypeId,
            "shell_references_type": shell.getTypeIdOfProperty("References"),
            "solver_type": solver.Proxy.Type,
            "solver_defaults": {
                "BeamReducedIntegration": bool(solver.BeamReducedIntegration),
                "BeamShellResultOutput3D": bool(solver.BeamShellResultOutput3D),
                "ExcludeBendingStiffness": bool(solver.ExcludeBendingStiffness),
            },
        }
    finally:
        app.closeDocument(doc.Name)


def _check_native_grouping(app: Any, objects_fem: Any) -> dict[str, Any]:
    """Exercise native mesh-set grouping before serializing one section."""

    import Fem
    import Part
    from femmesh import meshsetsgetter
    from femsolver.calculix import write_femelement_geometry
    from femtools import membertools

    doc = app.newDocument("R7NativeGrouping")
    try:
        analysis = objects_fem.makeAnalysis(doc, "Analysis")
        solver = objects_fem.makeSolverCalculiX(doc, "Solver")
        solver.AnalysisType = "static"
        analysis.addObject(solver)
        line = doc.addObject("Part::Feature", "Line")
        line.Shape = Part.makeLine(app.Vector(0, 0, 0), app.Vector(100, 0, 0))
        geometry = objects_fem.makeElementGeometry1D(doc, name="Beam")
        geometry.References = [(line, "Edge1")]
        analysis.addObject(geometry)
        rotation = objects_fem.makeElementRotation1D(doc, "Rotation")
        analysis.addObject(rotation)
        material = objects_fem.makeMaterialSolid(doc, "Material")
        values = material.Material
        values["Name"] = "Steel"
        values["YoungsModulus"] = "210000 MPa"
        values["PoissonRatio"] = "0.3"
        material.Material = values
        analysis.addObject(material)
        mesh = objects_fem.makeMeshGmsh(doc, "Mesh")
        mesh.Shape = line
        fem_mesh = Fem.FemMesh()
        fem_mesh.addNode(0, 0, 0, 1)
        fem_mesh.addNode(100, 0, 0, 2)
        fem_mesh.addEdge([1, 2], 1)
        mesh.FemMesh = fem_mesh
        mesh.ElementDimension = "1D"
        analysis.addObject(mesh)

        member = membertools.AnalysisMember(analysis)
        sets = meshsetsgetter.MeshSetsGetter(analysis, solver, mesh, member)
        sets.get_mesh_sets()
        _assert(len(sets.mat_geo_sets) == 1, sets.mat_geo_sets)
        mat_geo = sets.mat_geo_sets[0]
        _assert(mat_geo["ccx_elset"] == [1], mat_geo)
        _assert(mat_geo["beamsection_obj"] is geometry, mat_geo)
        _assert(list(mat_geo["beam_axis_m"]) == [0.0, 1.0, -0.0], mat_geo)
        output = io.StringIO()
        write_femelement_geometry.write_femelement_geometry(output, _WriterView(solver, sets.mat_geo_sets))
        _assert("*BEAM SECTION" in output.getvalue(), output.getvalue())
        return {
            "mat_geo_elset": mat_geo["ccx_elset_name"],
            "beam_axis_m": list(mat_geo["beam_axis_m"]),
            "section": "*BEAM SECTION",
        }
    finally:
        app.closeDocument(doc.Name)


class _WriterView:
    """Minimal native-writer view used only to call its section serializer."""

    def __init__(self, solver: Any, mat_geo_sets: list[dict[str, Any]]) -> None:
        self.solver_obj = solver
        self.mat_geo_sets = mat_geo_sets


def _writer_text(objects_fem: Any, app: Any, *, bending: bool, surface: bool) -> str:
    from femsolver.calculix import write_femelement_geometry

    doc = app.newDocument("R7WriterContract")
    try:
        solver = objects_fem.makeSolverCalculiX(doc, "Solver")
        solver.ExcludeBendingStiffness = bending
        solver.ModelSpace = "3D"
        if surface:
            geometry = objects_fem.makeElementGeometry2D(doc, thickness=3.5, name="Shell")
            geometry.Offset = 0.25
            mat_geo_sets = [
                {
                    "ccx_elset": [1],
                    "ccx_elset_name": "EShell",
                    "mat_obj_name": "Mat",
                    "shellthickness_obj": geometry,
                }
            ]
        else:
            geometry = objects_fem.makeElementGeometry1D(doc, name="Beam")
            geometry.SectionType = "Rectangular"
            geometry.RectWidth = 10.0
            geometry.RectHeight = 25.0
            mat_geo_sets = [
                {
                    "ccx_elset": [1],
                    "ccx_elset_name": "EBeam",
                    "mat_obj_name": "Mat",
                    "beamsection_obj": geometry,
                    "beam_axis_m": [0.0, 1.0, 0.0],
                }
            ]
        target = io.StringIO()
        write_femelement_geometry.write_femelement_geometry(
            target, _WriterView(solver, mat_geo_sets)
        )
        return target.getvalue()
    finally:
        app.closeDocument(doc.Name)


def _check_writer(objects_fem: Any, app: Any) -> dict[str, Any]:
    from femsolver.calculix import write_femelement_geometry

    doc = app.newDocument("R7WriterSections")
    try:
        solver = objects_fem.makeSolverCalculiX(doc, "Solver")
        solver.ModelSpace = "3D"
        sections: dict[str, str] = {}
        values = {
            "Rectangular": "10,25\n0, 1, 0\n",
            "Circular": "25\n0, 1, 0\n",
            "Pipe": "12.5,2\n0, 1, 0\n",
            "Elliptical": "10,25\n0, 1, 0\n",
            "Box": "10,25,2,2,2,2\n0, 1, 0\n",
        }
        for section_type, expected_geometry in values.items():
            geometry = objects_fem.makeElementGeometry1D(
                doc, sectiontype=section_type, name=f"Beam{section_type}"
            )
            target = io.StringIO()
            write_femelement_geometry.write_femelement_geometry(
                target,
                _WriterView(
                    solver,
                    [
                        {
                            "ccx_elset": [1],
                            "ccx_elset_name": "EBeam",
                            "mat_obj_name": "Mat",
                            "beamsection_obj": geometry,
                            "beam_axis_m": [0.0, 1.0, 0.0],
                        }
                    ],
                ),
            )
            text = target.getvalue()
            expected = "*BEAM SECTION, ELSET=EBeam, MATERIAL=Mat, SECTION="
            expected += "RECT\n" if section_type == "Rectangular" else "CIRC\n" if section_type in {"Circular", "Elliptical"} else "PIPE\n" if section_type == "Pipe" else "BOX\n"
            _assert(expected in text, f"{section_type} header changed: {text!r}")
            _assert(expected_geometry in text, f"{section_type} geometry changed: {text!r}")
            sections[section_type] = text.split("** Sections", 1)[-1].strip()

        solver.ExcludeBendingStiffness = True
        truss = objects_fem.makeElementGeometry1D(doc, name="Truss")
        truss.TrussArea = 10.0
        target = io.StringIO()
        write_femelement_geometry.write_femelement_geometry(
            target,
            _WriterView(
                solver,
                [
                    {
                        "ccx_elset": [1],
                        "ccx_elset_name": "ETruss",
                        "mat_obj_name": "Mat",
                        "beamsection_obj": truss,
                        "beam_axis_m": [0.0, 1.0, 0.0],
                    }
                ],
            ),
        )
        truss_text = target.getvalue()
        _assert("*SOLID SECTION, ELSET=ETruss, MATERIAL=Mat\n10\n" in truss_text, truss_text)

        shell_section_text = _writer_text(objects_fem, app, bending=False, surface=True)
        _assert("*SHELL SECTION, ELSET=EShell, MATERIAL=Mat, OFFSET=0.25\n3.5\n" in shell_section_text, shell_section_text)
        membrane_section_text = _writer_text(objects_fem, app, bending=True, surface=True)
        _assert("*MEMBRANE SECTION, ELSET=EShell, MATERIAL=Mat, OFFSET=0.25\n3.5\n" in membrane_section_text, membrane_section_text)
        return {
            "beam_sections": sections,
            "beam_exclude_bending": "*SOLID SECTION, ELSET=ETruss, MATERIAL=Mat",
            "shell_section": "*SHELL SECTION",
            "membrane_section": "*MEMBRANE SECTION",
        }
    finally:
        app.closeDocument(doc.Name)


def run() -> None:
    try:
        import FreeCAD as app  # type: ignore
        import ObjectsFem  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this probe with FreeCADCmd 1.1.3") from exc
    if getattr(app, "_R7NativeBeamShellContractRunning", False):
        return
    app._R7NativeBeamShellContractRunning = True
    factory_summary = _check_factories(app, ObjectsFem)
    writer_summary = _check_writer(ObjectsFem, app)
    grouping_summary = _check_native_grouping(app, ObjectsFem)
    print(json.dumps({"factories": factory_summary, "writer": writer_summary, "native_grouping": grouping_summary}, sort_keys=True))


# FreeCADCmd dispatches positional scripts under a filename-derived module
# name, so this executable intentionally calls run() unconditionally.
run()
