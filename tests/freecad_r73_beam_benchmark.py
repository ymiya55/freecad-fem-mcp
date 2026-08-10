"""R7.3 native CalculiX beam/truss accuracy benchmark.

Run this executable with FreeCADCmd 1.1.3.  It constructs one 1D line mesh
for a rectangular cantilever and one for an axial truss, assigning native
ElementGeometry1D and ElementRotation1D objects before running only the
CalculiXTools pipeline.  Tip displacements are compared with closed-form
Euler--Bernoulli and axial-bar calculations at a five-percent tolerance.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from statistics import median
from typing import Any, Iterable


L_MM = 1000.0
L_M = L_MM / 1000.0
WIDTH_M = 0.04
HEIGHT_M = 0.02
AREA_M2 = 0.0002
E_PA = 210.0e9
FORCE_BENDING_N = 100.0
FORCE_AXIAL_N = 10000.0
MOMENT_OF_INERTIA_M4 = WIDTH_M * HEIGHT_M**3 / 12.0
EXPECTED_BENDING_M = FORCE_BENDING_N * L_M**3 / (3.0 * E_PA * MOMENT_OF_INERTIA_M4)
EXPECTED_AXIAL_M = FORCE_AXIAL_N * L_M / (E_PA * AREA_M2)
RELATIVE_TOLERANCE = 0.05
MESH_SIZE_MM = 100.0


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AssertionError("{} is not numeric".format(label)) from exc
    if not math.isfinite(number):
        raise AssertionError("{} is not finite".format(label))
    return number


def _wait_job(registry: Any, job_id: str, timeout_s: float = 300.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        registry.wait(job_id, 50)
        summary = registry.get(job_id)
        if summary["state"] not in {"queued", "running"}:
            return summary
        try:
            from PySide import QtCore  # type: ignore

            QtCore.QCoreApplication.processEvents()
        except ImportError:
            pass
        time.sleep(0.05)
    raise AssertionError("job did not finish within {} seconds".format(timeout_s))


def _native_pipeline(results: Any) -> Any:
    values = results if isinstance(results, (list, tuple)) else [results]
    for value in values:
        if getattr(value, "TypeId", "") in {"Fem::FemPostPipeline", "Fem::FemPostPipelinePython"}:
            return value
    raise AssertionError("solver.Results did not contain FemPostPipeline")


def _blocks(data: Any) -> Iterable[Any]:
    get_count = getattr(data, "GetNumberOfBlocks", None)
    get_block = getattr(data, "GetBlock", None)
    if callable(get_count) and callable(get_block):
        count = min(max(int(get_count()), 0), 256)
        for index in range(count):
            block = get_block(index)
            if block is not None:
                yield from _blocks(block)
        return
    if data is not None:
        yield data


def _arrays(block: Any, association: str) -> Iterable[tuple[str, Any]]:
    getter = getattr(block, association, None)
    attributes = getter() if callable(getter) else None
    count_getter = getattr(attributes, "GetNumberOfArrays", None)
    array_getter = getattr(attributes, "GetArray", None)
    if not callable(count_getter) or not callable(array_getter):
        return
    for index in range(min(max(int(count_getter()), 0), 512)):
        array = array_getter(index)
        name_getter = getattr(array, "GetName", None)
        name = name_getter() if callable(name_getter) else None
        if name:
            yield str(name), array


def _normalise(name: Any) -> str:
    return "".join(character.lower() for character in str(name) if character.isalnum())


def _choose_displacement(arrays: list[tuple[str, Any]]) -> Any:
    ranked = []
    for name, array in arrays:
        normalized = _normalise(name)
        if any(alias in normalized for alias in ("displacement", "disp", "u")):
            ranked.append((0 if "displacement" in normalized else 1, name, array))
    if not ranked:
        raise AssertionError("native result had no displacement array")
    ranked.sort(key=lambda item: item[0])
    return ranked[0][2]


def _tuple(array: Any, index: int) -> list[float]:
    getter = getattr(array, "GetTuple", None)
    value = getter(index) if callable(getter) else getattr(array, "GetValue")(index)
    if isinstance(value, (list, tuple)):
        return [_finite(item, "result component") for item in value]
    return [_finite(value, "result value")]


def _tip_component(pipeline: Any, component: int) -> float:
    candidates: list[tuple[tuple[float, float, float], list[float]]] = []
    for block in _blocks(pipeline.Data):
        points = getattr(block, "GetPoints", lambda: None)()
        if points is None:
            continue
        try:
            count = min(max(int(points.GetNumberOfPoints()), 0), 200000)
        except (AttributeError, TypeError, ValueError):
            continue
        try:
            displacement = _choose_displacement(list(_arrays(block, "GetPointData")))
        except AssertionError:
            continue
        for index in range(count):
            candidates.append((points.GetPoint(index), _tuple(displacement, index)))
    if not candidates:
        raise AssertionError("no imported point displacement values")
    max_x = max(_finite(item[0][0], "point x") for item in candidates)
    values = [item[1][component] for item in candidates if item[0][0] >= max_x - 1e-6]
    if not values:
        raise AssertionError("no tip displacement values")
    # CalculiX/FreeCAD's mechanical result pipeline uses millimetres.
    return median(values) / 1000.0


def _run_line_analysis(
    operations: Any,
    doc: Any,
    registry: Any,
    line: Any,
    analysis_name: str,
    mesh_name: str,
    section: dict[str, Any],
    force: float,
    direction: list[float],
    expected: float,
    component: int,
    rotation: bool,
) -> dict[str, Any]:
    analysis = operations.create_analysis(analysis_name)
    operations.set_material(
        analysis["name"],
        {"youngs_modulus_pa": E_PA, "poisson_ratio": 0.3, "density_kg_m3": 7850.0},
    )
    operations.assign_element_geometry(
        analysis["name"],
        "beam_section",
        {
            "name": section["name"],
            "references": [{"object": line.Name, "sub_element": "Edge1"}],
            **{key: value for key, value in section.items() if key != "name"},
        },
    )
    if rotation:
        operations.assign_element_geometry(
            analysis["name"],
            "beam_rotation",
            {
                "name": section["name"] + "Rotation",
                "references": [{"object": line.Name, "sub_element": "Edge1"}],
                "rotation_rad": 0.0,
            },
        )
    operations.add_constraint(
        analysis["name"],
        "fixed",
        {"references": [{"object": line.Name, "sub_element": "Vertex1"}]},
    )
    operations.add_constraint(
        analysis["name"],
        "force",
        {
            "references": [{"object": line.Name, "sub_element": "Vertex2"}],
            "force": force,
            "direction": direction,
        },
    )
    mesh = operations.create_mesh(
        analysis["name"],
        mesh_name,
        element_dimension="1d",
        shape=line.Name,
        CharacteristicLengthMax=MESH_SIZE_MM,
        CharacteristicLengthMin=MESH_SIZE_MM,
    )
    gmsh = _wait_job(registry, registry.start_gmsh(doc.getObject(mesh["name"]))["id"])
    if gmsh["state"] != "completed":
        raise AssertionError({"gmsh_state": gmsh["state"], "gmsh_exit": gmsh.get("exit_code")})
    validation = operations.validate(analysis["name"])
    if not validation["valid"]:
        raise AssertionError({"validation": validation})
    solver = doc.getObject(analysis["solver"])
    if rotation and getattr(solver, "BeamReducedIntegration", None) is not False:
        raise AssertionError("normal beam geometry must select full integration")
    calculix = _wait_job(registry, registry.start_calculix(solver)["id"])
    if calculix["state"] != "completed":
        raise AssertionError(
            {
                "calculix_state": calculix["state"],
                "calculix_exit": calculix.get("exit_code"),
                "calculix_output": calculix.get("output", "")[-512:],
            }
        )
    pipeline = _native_pipeline(getattr(solver, "Results", None))
    measured = abs(_tip_component(pipeline, component))
    relative_error = abs(measured - expected) / expected
    if relative_error > RELATIVE_TOLERANCE:
        raise AssertionError(
            {
                "expected_displacement_m": expected,
                "measured_displacement_m": measured,
                "relative_error": relative_error,
            }
        )
    return {
        "expected_displacement_m": expected,
        "measured_displacement_m": measured,
        "relative_error": relative_error,
        "mesh_dimension": "1D",
        "gmsh": {"state": gmsh["state"], "exit_code": gmsh.get("exit_code")},
        "calculix": {"state": calculix["state"], "exit_code": calculix.get("exit_code")},
        "results_type": str(getattr(pipeline, "TypeId", "")),
    }


def run_benchmark() -> dict[str, Any]:
    try:
        import FreeCAD as App  # type: ignore
        import ObjectsFem  # type: ignore
        import Part  # type: ignore
    except ImportError as exc:
        raise RuntimeError("run with FreeCADCmd 1.1.3") from exc
    guard_name = "_FreeCADFEMMCPR73BeamBenchmarkRunning"
    if getattr(App, guard_name, False):
        return {"ok": True, "reentered": True}
    setattr(App, guard_name, True)
    addon_root = Path(__file__).resolve().parents[1] / "addon"
    if str(addon_root) not in sys.path:
        sys.path.insert(0, str(addon_root))
    from FreeCADFEMMCP.jobs import QProcessJobRegistry
    from FreeCADFEMMCP.operations import FreeCADOperations

    doc = App.newDocument("R73BeamBenchmark")
    try:
        line = doc.addObject("Part::Feature", "ReferenceLine")
        line.Shape = Part.makeLine(App.Vector(0.0, 0.0, 0.0), App.Vector(L_MM, 0.0, 0.0))
        doc.recompute()
        operations = FreeCADOperations(app=App, objects_fem=ObjectsFem, allowed_roots=[str(Path.cwd())])
        registry = QProcessJobRegistry()
        bending = _run_line_analysis(
            operations,
            doc,
            registry,
            line,
            "BeamCantileverAnalysis",
            "BeamCantileverMesh1D",
            {"name": "BeamRectangular", "section_type": "rectangular", "rect_width_m": WIDTH_M, "rect_height_m": HEIGHT_M},
            FORCE_BENDING_N,
            [0.0, 0.0, -1.0],
            EXPECTED_BENDING_M,
            2,
            True,
        )
        truss = _run_line_analysis(
            operations,
            doc,
            registry,
            line,
            "TrussAxialAnalysis",
            "TrussAxialMesh1D",
            {"name": "TrussSection", "section_type": "truss", "truss_area_m2": AREA_M2},
            FORCE_AXIAL_N,
            [1.0, 0.0, 0.0],
            EXPECTED_AXIAL_M,
            0,
            False,
        )
        report = {
            "ok": True,
            "formulation": {"beam": "rectangular", "truss": "truss"},
            "theory": {
                "cantilever_tip_displacement_m": EXPECTED_BENDING_M,
                "truss_tip_displacement_m": EXPECTED_AXIAL_M,
            },
            "measured": {"cantilever": bending, "truss": truss},
            "tolerance": RELATIVE_TOLERANCE,
        }
        print(json.dumps(report, separators=(",", ":"), sort_keys=True))
        return report
    finally:
        App.closeDocument(doc.Name)
        setattr(App, guard_name, False)


# FreeCADCmd positional dispatch uses a filename-derived module name.
run_benchmark()
