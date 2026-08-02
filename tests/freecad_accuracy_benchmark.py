"""FreeCADCmd axial-bar accuracy benchmark for the native FEM vertical slice.

This is intentionally an executable benchmark rather than a pytest test: it
requires a real FreeCAD 1.1.3 installation with the bundled Gmsh and
CalculiX tools.  Run it with ``FreeCADCmd`` (or set ``FREECAD_CMD`` for the
launcher at the bottom of this file).  It constructs a 100 mm x 10 mm x 10 mm
bar, applies a 1,000 N axial load, and checks representative interior stress
and load-end displacement against F/A and FL/(EA) within 2 percent.

No legacy solver/tool module is imported.  All values crossing the FreeCAD
boundary are explicit: geometry and displacement are in mm, material modulus
and stress are in MPa, force is in N, and the reference calculation is SI.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from statistics import median
from typing import Any, Iterable


L_MM = 100.0
WIDTH_MM = 10.0
HEIGHT_MM = 10.0
AREA_M2 = (WIDTH_MM / 1000.0) * (HEIGHT_MM / 1000.0)
L_M = L_MM / 1000.0
E_PA = 210.0e9
FORCE_N = 1000.0
EXPECTED_STRESS_PA = FORCE_N / AREA_M2
EXPECTED_DISPLACEMENT_M = FORCE_N * L_M / (E_PA * AREA_M2)
RELATIVE_TOLERANCE = 0.02
MESH_SIZE_MM = 2.5


def _finite(value: Any, label: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise AssertionError("{} is not numeric".format(label)) from exc
    if not math.isfinite(converted):
        raise AssertionError("{} is not finite".format(label))
    return converted


def _wait_job(registry: Any, job_id: str, timeout_s: float = 180.0) -> dict[str, Any]:
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
    raise AssertionError("job {} did not finish within {} seconds".format(job_id, timeout_s))


def _face_at_x(shape: Any, x_target: float) -> str:
    faces = list(getattr(shape, "Faces", []) or [])
    if not faces:
        raise AssertionError("bar has no faces")
    selected = min(
        enumerate(faces, 1),
        key=lambda item: abs(float(item[1].CenterOfMass.x) - x_target),
    )
    return "Face{}".format(selected[0])


def _native_pipeline(results: Any) -> Any:
    values = results if isinstance(results, (list, tuple)) else [results]
    for value in values:
        if getattr(value, "TypeId", "") == "Fem::FemPostPipeline":
            return value
    raise AssertionError("solver.Results did not contain Fem::FemPostPipeline")


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
    if attributes is None:
        return
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


def _choose_array(arrays: list[tuple[str, Any]], kind: str) -> tuple[str, Any]:
    aliases = {
        "displacement": ("displacement", "disp", "u"),
        "stress": ("stress", "sxx", "sigma", "s11"),
    }[kind]
    ranked = []
    for name, array in arrays:
        normalized = _normalise(name)
        rank = next((index for index, alias in enumerate(aliases) if alias in normalized), None)
        if rank is not None:
            ranked.append((rank, name, array))
    if not ranked:
        raise AssertionError("native result had no {} array".format(kind))
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1], ranked[0][2]


def _tuple(array: Any, index: int) -> list[float]:
    getter = getattr(array, "GetTuple", None)
    if callable(getter):
        value = getter(index)
    else:
        getter = getattr(array, "GetValue", None)
        value = getter(index) if callable(getter) else None
    if isinstance(value, (list, tuple)):
        return [_finite(item, "result component") for item in value]
    return [_finite(value, "result value")]


def _point_displacement(pipeline: Any) -> tuple[float, str]:
    candidates: list[tuple[Any, Any]] = []
    for block in _blocks(pipeline.Data):
        arrays = list(_arrays(block, "GetPointData"))
        points = getattr(block, "GetPoints", lambda: None)()
        if points is None:
            continue
        try:
            point_count = min(max(int(points.GetNumberOfPoints()), 0), 200000)
        except (AttributeError, TypeError, ValueError):
            continue
        try:
            _, displacement = _choose_array(arrays, "displacement")
        except AssertionError:
            continue
        for index in range(point_count):
            coordinate = points.GetPoint(index)
            candidates.append((coordinate, _tuple(displacement, index)))
    if not candidates:
        raise AssertionError("no point displacement values were imported")
    max_x = max(_finite(item[0][0], "point x") for item in candidates)
    end = [item[1][0] for item in candidates if item[0][0] >= max_x - 1.0e-6]
    if not end:
        raise AssertionError("no load-end displacement nodes were found")
    # The x displacement should be essentially uniform over the loaded end;
    # median rejects a single noisy/duplicate point without hiding a real error.
    return abs(median(end)), "mm"


def _interior_stress(pipeline: Any) -> tuple[float, str]:
    values: list[float] = []
    for block in _blocks(pipeline.Data):
        arrays = list(_arrays(block, "GetCellData"))
        point_mode = not arrays
        if point_mode:
            arrays = list(_arrays(block, "GetPointData"))
        try:
            _, stress = _choose_array(arrays, "stress")
        except AssertionError:
            continue
        tuples = min(max(int(stress.GetNumberOfTuples()), 0), 200000)
        # Prefer cell centers when available; otherwise use all values because
        # point stress at the loaded/fixed face can be singular.
        centers = []
        cells = getattr(block, "GetCell", None)
        points = getattr(block, "GetPoints", lambda: None)()
        for index in range(tuples):
            if callable(cells):
                try:
                    center = cells(index).GetCenter()
                    centers.append(float(center.x))
                except (AttributeError, TypeError, ValueError):
                    centers.append(float("nan"))
            elif point_mode and points is not None:
                try:
                    centers.append(float(points.GetPoint(index)[0]))
                except (AttributeError, IndexError, TypeError, ValueError):
                    centers.append(float("nan"))
            else:
                centers.append(float("nan"))
        finite_centers = [value for value in centers if math.isfinite(value)]
        if finite_centers:
            min_x, max_x = min(finite_centers), max(finite_centers)
            interior = [index for index, value in enumerate(centers) if math.isfinite(value) and min_x + 0.25 * (max_x - min_x) <= value <= max_x - 0.25 * (max_x - min_x)]
        else:
            interior = list(range(tuples))
        for index in interior:
            component = _tuple(stress, index)[0]
            values.append(abs(component))
    if not values:
        raise AssertionError("no representative interior stress values were imported")
    return median(values), "MPa"


def run_benchmark() -> dict[str, Any]:
    try:
        import FreeCAD as App  # type: ignore
        import ObjectsFem  # type: ignore
    except ImportError as exc:
        raise RuntimeError("run with FreeCADCmd 1.1.3") from exc

    guard_name = "_FreeCADFEMMCPAccuracyRunning"
    if getattr(App, guard_name, False):
        raise RuntimeError("accuracy benchmark is already running in this FreeCAD process")
    setattr(App, guard_name, True)
    addon_root = Path(__file__).resolve().parents[1] / "addon"
    if str(addon_root) not in sys.path:
        sys.path.insert(0, str(addon_root))
    from FreeCADFEMMCP.jobs import QProcessJobRegistry
    from FreeCADFEMMCP.operations import FreeCADOperations

    doc = App.newDocument("FreeCADFEMMCPAccuracy")
    try:
        bar = doc.addObject("Part::Box", "AxialBar")
        bar.Length, bar.Width, bar.Height = L_MM, WIDTH_MM, HEIGHT_MM
        doc.recompute()
        left_face = _face_at_x(bar.Shape, 0.0)
        right_face = _face_at_x(bar.Shape, L_MM)
        operations = FreeCADOperations(app=App, objects_fem=ObjectsFem, allowed_roots=[str(Path.cwd())])
        analysis = operations.create_analysis("AxialAnalysis")
        operations.set_material(analysis["name"], {"youngs_modulus_pa": E_PA, "poisson_ratio": 0.3, "density_kg_m3": 7850.0})
        operations.add_constraint(analysis["name"], "fixed", {"references": [{"object": "AxialBar", "sub_element": left_face}]})
        operations.add_constraint(analysis["name"], "force", {"references": [{"object": "AxialBar", "sub_element": right_face}], "force": FORCE_N, "direction": [1.0, 0.0, 0.0]})
        mesh = operations.create_mesh(analysis["name"], "AxialMesh", shape="AxialBar", ElementOrder="1st", CharacteristicLengthMax=MESH_SIZE_MM, CharacteristicLengthMin=MESH_SIZE_MM)
        registry = QProcessJobRegistry()
        gmsh_job = registry.start_gmsh(doc.getObject(mesh["name"]))
        gmsh_result = _wait_job(registry, gmsh_job["id"])
        assert gmsh_result["state"] == "completed", gmsh_result
        validation = operations.validate(analysis["name"])
        assert validation["valid"], validation
        solver = doc.getObject(analysis["solver"])
        solver_job = registry.start_calculix(solver)
        solver_result = _wait_job(registry, solver_job["id"], 300.0)
        assert solver_result["state"] == "completed", solver_result
        pipeline = _native_pipeline(getattr(solver, "Results", None))
        displacement_mm, displacement_unit = _point_displacement(pipeline)
        stress_mpa, stress_unit = _interior_stress(pipeline)
        measured_displacement_m = displacement_mm / 1000.0
        measured_stress_pa = stress_mpa * 1.0e6
        displacement_error = abs(measured_displacement_m - EXPECTED_DISPLACEMENT_M) / EXPECTED_DISPLACEMENT_M
        stress_error = abs(measured_stress_pa - EXPECTED_STRESS_PA) / EXPECTED_STRESS_PA
        assert displacement_error <= RELATIVE_TOLERANCE, (displacement_mm, EXPECTED_DISPLACEMENT_M * 1000.0, displacement_error)
        assert stress_error <= RELATIVE_TOLERANCE, (stress_mpa, EXPECTED_STRESS_PA / 1.0e6, stress_error)
        report = {
            "geometry": {"length_mm": L_MM, "width_mm": WIDTH_MM, "height_mm": HEIGHT_MM, "mesh_size_mm": MESH_SIZE_MM},
            "material": {"youngs_modulus_pa": E_PA, "area_m2": AREA_M2},
            "load": {"force_n": FORCE_N},
            "theory": {"stress_pa": EXPECTED_STRESS_PA, "displacement_m": EXPECTED_DISPLACEMENT_M},
            "measured": {"stress": stress_mpa, "stress_unit": stress_unit, "displacement": displacement_mm, "displacement_unit": displacement_unit},
            "relative_error": {"stress": stress_error, "displacement": displacement_error},
            "jobs": {"gmsh": gmsh_result, "calculix": solver_result},
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return report
    finally:
        App.closeDocument(doc.Name)
        setattr(App, guard_name, False)


if __name__ in {"__main__", Path(__file__).stem}:
    run_benchmark()
