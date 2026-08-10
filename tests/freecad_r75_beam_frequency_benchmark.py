"""Portable native 1D beam frequency and 3D-result-output benchmark.

The benchmark runs a rectangular Euler--Bernoulli cantilever through the
CalculiXTools pipeline twice, with SolverCalculiX.BeamShellResultOutput3D
disabled and enabled.  It records the native writer keyword and imported
FemPostPipeline frame/data shape for each run.  No input deck is injected and
no legacy solver is used.
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


L_M = 1.0
WIDTH_M = 0.04
HEIGHT_M = 0.02
AREA_M2 = WIDTH_M * HEIGHT_M
E_PA = 210.0e9
DENSITY_KG_M3 = 7850.0
INERTIA_M4 = WIDTH_M * HEIGHT_M**3 / 12.0
BETA1 = 1.875104068711961
EXPECTED_FREQUENCY_HZ = BETA1**2 / (2.0 * math.pi * L_M**2) * math.sqrt(
    E_PA * INERTIA_M4 / (DENSITY_KG_M3 * AREA_M2)
)
RELATIVE_TOLERANCE = 0.05


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        text = str(value).strip().split()
        try:
            number = float(text[0])
        except (IndexError, TypeError, ValueError, OverflowError) as nested:
            raise AssertionError(f"{label} is not numeric") from nested
    if not math.isfinite(number):
        raise AssertionError(f"{label} is not finite")
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
    raise AssertionError("job did not finish within {:.0f} seconds".format(timeout_s))


def _pipeline(results: Any) -> Any:
    values = results if isinstance(results, (list, tuple)) else [results]
    for value in values:
        if getattr(value, "TypeId", "") in {"Fem::FemPostPipeline", "Fem::FemPostPipelinePython"}:
            return value
    raise AssertionError("solver.Results did not contain FemPostPipeline")


def _frame_frequency(pipeline: Any) -> float:
    enumerate_frames = getattr(pipeline, "getEnumerationsOfProperty", None)
    values = enumerate_frames("Frame") if callable(enumerate_frames) else []
    if not isinstance(values, (list, tuple)) or not values:
        raise AssertionError("native frequency pipeline has no Frame enumeration")
    frequency = _finite(values[0], "native Frame frequency")
    if frequency <= 0.0:
        raise AssertionError("native Frame frequency is not positive")
    return frequency


def _data_shape(data: Any) -> dict[str, Any]:
    """Summarize imported VTK blocks without importing VTK."""

    get_count = getattr(data, "GetNumberOfBlocks", None)
    get_block = getattr(data, "GetBlock", None)
    if callable(get_count) and callable(get_block):
        count = min(max(int(get_count()), 0), 256)
        blocks = [get_block(index) for index in range(count)]
    else:
        blocks = [data]
    point_counts: list[int] = []
    fields: set[str] = set()
    for block in blocks:
        if block is None:
            continue
        points = getattr(block, "GetPoints", lambda: None)()
        if points is not None:
            try:
                point_counts.append(min(max(int(points.GetNumberOfPoints()), 0), 1_000_000))
            except (AttributeError, TypeError, ValueError):
                pass
        point_data = getattr(block, "GetPointData", lambda: None)()
        get_arrays = getattr(point_data, "GetNumberOfArrays", None)
        get_array = getattr(point_data, "GetArray", None)
        if callable(get_arrays) and callable(get_array):
            for index in range(min(max(int(get_arrays()), 0), 512)):
                array = get_array(index)
                get_name = getattr(array, "GetName", None)
                if callable(get_name) and get_name():
                    fields.add(str(get_name()))
    return {
        "blocks": len([block for block in blocks if block is not None]),
        "point_counts": point_counts,
        "point_fields": sorted(fields),
    }


class _WriterMember:
    geos_beamsection = [object()]
    geos_shellthickness: list[Any] = []
    geos_fluidsection: list[Any] = []
    cons_fixed: list[Any] = []
    cons_displacement: list[Any] = []
    cons_rigidbody: list[Any] = []
    cons_contact: list[Any] = []


class _WriterView:
    analysis_type = "frequency"
    member = _WriterMember()

    def __init__(self, solver: Any) -> None:
        self.solver_obj = solver


def _writer_keyword(objects_fem: Any, app: Any, output_3d: bool) -> str:
    from femsolver.calculix import write_step_output

    parent_name = getattr(getattr(app, "ActiveDocument", None), "Name", None)
    doc = app.newDocument("R75BeamWriter")
    try:
        solver = objects_fem.makeSolverCalculiX(doc, "Solver")
        solver.BeamShellResultOutput3D = output_3d
        target = io.StringIO()
        write_step_output.write_step_output(target, _WriterView(solver))
        text = target.getvalue()
        expected = "*NODE FILE, OUTPUT=3d" if output_3d else "*NODE FILE, OUTPUT=2d"
        if expected not in text:
            raise AssertionError(f"native writer omitted {expected}")
        return expected
    finally:
        app.closeDocument(doc.Name)
        if parent_name and callable(getattr(app, "setActiveDocument", None)):
            app.setActiveDocument(parent_name)


def _run_case(
    operations: Any,
    app: Any,
    objects_fem: Any,
    registry: Any,
    line: Any,
    output_3d: bool,
    suffix: str,
) -> dict[str, Any]:
    analysis = operations.create_analysis(
        "BeamFrequencyAnalysis" + suffix,
        "frequency",
        eigenmodes_count=1,
    )
    operations.set_material(
        analysis["name"],
        {
            "youngs_modulus_pa": E_PA,
            "poisson_ratio": 0.3,
            "density_kg_m3": DENSITY_KG_M3,
        },
    )
    operations.assign_element_geometry(
        analysis["name"],
        "beam_section",
        {
            "name": "BeamRectangular" + suffix,
            "references": [{"object": line.Name, "sub_element": "Edge1"}],
            "section_type": "rectangular",
            "rect_width_m": WIDTH_M,
            "rect_height_m": HEIGHT_M,
        },
    )
    operations.assign_element_geometry(
        analysis["name"],
        "beam_rotation",
        {
            "name": "BeamRotation" + suffix,
            "references": [{"object": line.Name, "sub_element": "Edge1"}],
            "rotation_rad": 0.0,
        },
    )
    operations.add_constraint(
        analysis["name"],
        "fixed",
        {"references": [{"object": line.Name, "sub_element": "Vertex1"}]},
    )
    mesh = operations.create_mesh(
        analysis["name"],
        "BeamFrequencyMesh" + suffix,
        element_dimension="1d",
        shape=line.Name,
        CharacteristicLengthMax=100.0,
        CharacteristicLengthMin=100.0,
    )
    gmsh = _wait_job(registry, registry.start_gmsh(app.ActiveDocument.getObject(mesh["name"]))["id"])
    if gmsh["state"] != "completed":
        raise AssertionError({"gmsh": gmsh})
    solver = app.ActiveDocument.getObject(analysis["solver"])
    if not hasattr(solver, "BeamShellResultOutput3D"):
        raise AssertionError("native solver lacks BeamShellResultOutput3D")
    solver.BeamShellResultOutput3D = output_3d
    validation = operations.validate(analysis["name"])
    if not validation["valid"]:
        raise AssertionError({"validation": validation})
    calculix = _wait_job(registry, registry.start_calculix(solver)["id"])
    if calculix["state"] != "completed":
        raise AssertionError(
            {
                "calculix_state": calculix["state"],
                "calculix_exit": calculix.get("exit_code"),
                "calculix_output_tail": calculix.get("output", "")[-512:],
            }
        )
    pipeline = _pipeline(getattr(solver, "Results", None))
    measured = _frame_frequency(pipeline)
    relative_error = abs(measured - EXPECTED_FREQUENCY_HZ) / EXPECTED_FREQUENCY_HZ
    if relative_error > RELATIVE_TOLERANCE:
        raise AssertionError(
            {
                "expected_frequency_hz": EXPECTED_FREQUENCY_HZ,
                "measured_frequency_hz": measured,
                "relative_error": relative_error,
            }
        )
    return {
        "beam_shell_result_output_3d": output_3d,
        "writer_keyword": _writer_keyword(objects_fem, app, output_3d),
        "measured_frequency_hz": measured,
        "frame_values": [str(value) for value in pipeline.getEnumerationsOfProperty("Frame")[:8]],
        "data": _data_shape(getattr(pipeline, "Data", None)),
        "relative_error": relative_error,
        "mesh_dimension": "1D",
        "gmsh": {"state": gmsh["state"], "exit_code": gmsh.get("exit_code")},
        "calculix": {"state": calculix["state"], "exit_code": calculix.get("exit_code")},
    }


def run_benchmark() -> dict[str, Any]:
    try:
        import FreeCAD as app  # type: ignore
        import ObjectsFem  # type: ignore
        import Part  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this benchmark with FreeCADCmd 1.1.3") from exc
    guard_name = "_FreeCADFEMMCPR75BeamFrequencyRunning"
    if getattr(app, guard_name, False):
        return {"ok": True, "reentered": True}
    setattr(app, guard_name, True)
    script_path = Path(globals().get("__file__", Path.cwd() / "tests" / "freecad_r75_beam_frequency_benchmark.py"))
    addon_root = script_path.resolve().parents[1] / "addon"
    if str(addon_root) not in sys.path:
        sys.path.insert(0, str(addon_root))
    from FreeCADFEMMCP.jobs import QProcessJobRegistry  # type: ignore
    from FreeCADFEMMCP.operations import FreeCADOperations  # type: ignore

    doc = app.newDocument("R75BeamFrequencyBenchmark")
    try:
        line = doc.addObject("Part::Feature", "ReferenceLine")
        line.Shape = Part.makeLine(app.Vector(0.0, 0.0, 0.0), app.Vector(L_M * 1000.0, 0.0, 0.0))
        doc.recompute()
        operations = FreeCADOperations(app=app, objects_fem=ObjectsFem, allowed_roots=[str(Path.cwd())])
        registry = QProcessJobRegistry()
        cases = {
            str(output_3d).lower(): _run_case(
                operations,
                app,
                ObjectsFem,
                registry,
                line,
                output_3d,
                "3D" if output_3d else "2D",
            )
            for output_3d in (False, True)
        }
        report = {
            "ok": True,
            "source_dimension": "1D",
            "theory": {
                "equation": "beta1^2/(2*pi*L^2)*sqrt(E*I/(rho*A))",
                "frequency_hz": EXPECTED_FREQUENCY_HZ,
            },
            "tolerance": RELATIVE_TOLERANCE,
            "cases": cases,
        }
        print(json.dumps(report, separators=(",", ":"), sort_keys=True))
        return report
    finally:
        app.closeDocument(doc.Name)
        setattr(app, guard_name, False)


# FreeCADCmd positional dispatch uses a filename-derived module name.
run_benchmark()
