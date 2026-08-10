"""R7.2 native membrane patch benchmark.

This executable benchmark requires FreeCAD 1.1.3 with its bundled Gmsh and
CalculiX tools.  It uses the Addon operations and native ``CalculiXTools``
pipeline only.  A square membrane patch is prescribed a uniform in-plane
extension and the imported stress/displacement are compared with the analytic
plane-stress result at a five-percent tolerance.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from statistics import median
from typing import Any, Iterable


SIDE_MM = 100.0
THICKNESS_M = 0.001
EXTENSION_M = 0.0001
E_PA = 210.0e9
NU = 0.3
MESH_SIZE_MM = 5.0
EXPECTED_STRESS_PA = E_PA * EXTENSION_M / (SIDE_MM / 1000.0)
EXPECTED_DISPLACEMENT_M = EXTENSION_M
RELATIVE_TOLERANCE = 0.05


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


def _edge_at_x(shape: Any, x_target: float) -> str:
    edges = list(getattr(shape, "Edges", []) or [])
    if not edges:
        raise AssertionError("patch has no edges")
    selected = min(
        enumerate(edges, 1),
        key=lambda item: abs(float(item[1].CenterOfMass.x) - x_target),
    )
    return "Edge{}".format(selected[0])


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
    value = getter(index) if callable(getter) else getattr(array, "GetValue")(index)
    if isinstance(value, (list, tuple)):
        return [_finite(item, "result component") for item in value]
    return [_finite(value, "result value")]


def _right_edge_displacement(pipeline: Any) -> float:
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
            _, displacement = _choose_array(list(_arrays(block, "GetPointData")), "displacement")
        except AssertionError:
            continue
        for index in range(count):
            candidates.append((points.GetPoint(index), _tuple(displacement, index)))
    if not candidates:
        raise AssertionError("no imported point displacement values")
    max_x = max(_finite(item[0][0], "point x") for item in candidates)
    values = [item[1][0] for item in candidates if item[0][0] >= max_x - 1e-6]
    if not values:
        raise AssertionError("no right-edge displacement values")
    # FreeCAD's mechanical result pipeline reports displacement in mm.
    return abs(median(values)) / 1000.0


def _interior_stress(pipeline: Any) -> float:
    values: list[float] = []
    for block in _blocks(pipeline.Data):
        arrays = list(_arrays(block, "GetCellData"))
        if not arrays:
            arrays = list(_arrays(block, "GetPointData"))
        try:
            _, stress = _choose_array(arrays, "stress")
        except AssertionError:
            continue
        count = min(max(int(stress.GetNumberOfTuples()), 0), 200000)
        # M3D3/M3D6 result cells can trigger a VTK cell-center crash in the
        # FreeCAD 1.1 importer.  The patch is uniform, so robustly use all
        # finite stress tuples without walking native cell objects.
        for index in range(count):
            # Native stress arrays are imported in MPa, so convert to SI Pa.
            try:
                values.append(abs(_tuple(stress, index)[0]) * 1.0e6)
            except (AttributeError, IndexError, TypeError, ValueError):
                continue
    if not values:
        raise AssertionError("no imported interior stress values")
    return median(values)


def _shell_pressure_smoke(
    operations: Any,
    doc: Any,
    patch: Any,
    left_edge: str,
    registry: Any,
) -> dict[str, Any]:
    """Run a small native shell pressure deck to pin the pressure contract.

    Membrane M3D3 elements intentionally reject CalculiX's face-pressure
    card.  A shell section is the supported pressure formulation, so exercise
    it in a separate analysis and require a completed native CalculiX job.
    """

    analysis = operations.create_analysis("ShellPressureAnalysis")
    operations.set_material(
        analysis["name"],
        {"youngs_modulus_pa": E_PA, "poisson_ratio": NU, "density_kg_m3": 7850.0},
    )
    operations.assign_element_geometry(
        analysis["name"],
        "shell",
        {
            "name": "ShellPressureGeometry",
            "formulation": "shell",
            "references": [{"object": patch.Name, "sub_element": "Face1"}],
            "thickness_m": THICKNESS_M,
            "offset": 0.0,
        },
    )
    operations.add_constraint(
        analysis["name"],
        "fixed",
        {"references": [{"object": patch.Name, "sub_element": left_edge}]},
    )
    pressure = operations.add_constraint(
        analysis["name"],
        "pressure",
        {
            "references": [{"object": patch.Name, "sub_element": "Face1"}],
            "pressure": 1000.0,
        },
    )
    mesh = operations.create_mesh(
        analysis["name"],
        "ShellPressureMesh2D",
        element_dimension="2d",
        shape=patch.Name,
        CharacteristicLengthMax=MESH_SIZE_MM,
        CharacteristicLengthMin=MESH_SIZE_MM,
    )
    gmsh = _wait_job(registry, registry.start_gmsh(doc.getObject(mesh["name"]))["id"])
    if gmsh["state"] != "completed":
        raise AssertionError({"shell_gmsh_state": gmsh["state"], "shell_gmsh_exit": gmsh.get("exit_code")})
    validation = operations.validate(analysis["name"])
    if not validation["valid"]:
        raise AssertionError({"shell_validation": validation})
    solver = doc.getObject(analysis["solver"])
    calculix = _wait_job(registry, registry.start_calculix(solver)["id"])
    if calculix["state"] != "completed":
        raise AssertionError(
            {
                "shell_calculix_state": calculix["state"],
                "shell_calculix_exit": calculix.get("exit_code"),
                "shell_calculix_output": calculix.get("output", "")[-512:],
            }
        )
    results = getattr(solver, "Results", None)
    try:
        pipeline = _native_pipeline(results)
    except AssertionError as exc:
        raise AssertionError({"shell_results_type": str(getattr(results, "TypeId", ""))}) from exc
    result_type = str(getattr(pipeline, "TypeId", ""))
    return {
        "formulation": "shell",
        "pressure_kind": pressure["kind"],
        "mesh_dimension": "2D",
        "gmsh": {"state": gmsh["state"], "exit_code": gmsh.get("exit_code")},
        "calculix": {"state": calculix["state"], "exit_code": calculix.get("exit_code")},
        "results_type": result_type,
        "validation": {"valid": validation["valid"], "diagnostic_count": len(validation["diagnostics"])},
    }


def run_benchmark() -> dict[str, Any]:
    try:
        import FreeCAD as App  # type: ignore
        import ObjectsFem  # type: ignore
        import Part  # type: ignore
    except ImportError as exc:
        raise RuntimeError("run with FreeCADCmd 1.1.3") from exc
    guard_name = "_FreeCADFEMMCPR72ShellBenchmarkRunning"
    if getattr(App, guard_name, False):
        return {"ok": True, "reentered": True}
    setattr(App, guard_name, True)
    addon_root = Path(__file__).resolve().parents[1] / "addon"
    if str(addon_root) not in sys.path:
        sys.path.insert(0, str(addon_root))
    from FreeCADFEMMCP.jobs import QProcessJobRegistry
    from FreeCADFEMMCP.operations import FreeCADOperations

    doc = App.newDocument("R72MembranePatch")
    try:
        patch = doc.addObject("Part::Feature", "MembranePatch")
        patch.Shape = Part.makePlane(SIDE_MM, SIDE_MM)
        doc.recompute()
        left_edge = _edge_at_x(patch.Shape, 0.0)
        right_edge = _edge_at_x(patch.Shape, SIDE_MM)
        operations = FreeCADOperations(app=App, objects_fem=ObjectsFem, allowed_roots=[str(Path.cwd())])
        analysis = operations.create_analysis("MembraneAnalysis")
        operations.set_material(
            analysis["name"],
            {"youngs_modulus_pa": E_PA, "poisson_ratio": NU, "density_kg_m3": 7850.0},
        )
        operations.assign_element_geometry(
            analysis["name"],
            "shell",
            {
                "name": "MembraneGeometry",
                "formulation": "membrane",
                "references": [{"object": patch.Name, "sub_element": "Face1"}],
                "thickness_m": THICKNESS_M,
                "offset": 0.0,
            },
        )
        operations.add_constraint(
            analysis["name"],
            "fixed",
            {"references": [{"object": patch.Name, "sub_element": left_edge}]},
        )
        operations.add_constraint(
            analysis["name"],
            "displacement",
            {
                "references": [{"object": patch.Name, "sub_element": right_edge}],
                "x": EXTENSION_M,
                "xFree": False,
                "yFree": True,
                "zFree": True,
            },
        )
        # Exercise the existing force native route with a bounded near-zero
        # load; the prescribed extension remains the analytic patch load case.
        # CalculiX rejects a literal zero CLOAD on some FreeCAD 1.1 builds, so
        # keep a finite non-zero value negligible relative to the response.
        force_route = operations.add_constraint(
            analysis["name"],
            "force",
            {"references": [{"object": patch.Name, "sub_element": "Face1"}], "force": 1.0e-9, "direction": [1.0, 0.0, 0.0]},
        )
        mesh = operations.create_mesh(
            analysis["name"],
            "MembraneMesh2D",
            element_dimension="2d",
            shape=patch.Name,
            CharacteristicLengthMax=MESH_SIZE_MM,
            CharacteristicLengthMin=MESH_SIZE_MM,
        )
        registry = QProcessJobRegistry()
        gmsh_result = _wait_job(registry, registry.start_gmsh(doc.getObject(mesh["name"]))["id"])
        if gmsh_result["state"] != "completed":
            raise AssertionError({"gmsh_state": gmsh_result["state"], "gmsh_exit": gmsh_result.get("exit_code")})
        validation = operations.validate(analysis["name"])
        if not validation["valid"]:
            raise AssertionError({"validation": validation})
        solver = doc.getObject(analysis["solver"])
        calculix_result = _wait_job(registry, registry.start_calculix(solver)["id"])
        if calculix_result["state"] != "completed":
            raise AssertionError(
                {
                    "calculix_state": calculix_result["state"],
                    "calculix_exit": calculix_result.get("exit_code"),
                    "calculix_output": calculix_result.get("output", "")[-512:],
                }
            )
        pipeline = _native_pipeline(getattr(solver, "Results", None))
        measured_displacement = _right_edge_displacement(pipeline)
        measured_stress = _interior_stress(pipeline)
        displacement_error = abs(measured_displacement - EXPECTED_DISPLACEMENT_M) / EXPECTED_DISPLACEMENT_M
        stress_error = abs(measured_stress - EXPECTED_STRESS_PA) / EXPECTED_STRESS_PA
        if displacement_error > RELATIVE_TOLERANCE or stress_error > RELATIVE_TOLERANCE:
            raise AssertionError(
                {
                    "expected_displacement_m": EXPECTED_DISPLACEMENT_M,
                    "measured_displacement_m": measured_displacement,
                    "expected_stress_pa": EXPECTED_STRESS_PA,
                    "measured_stress_pa": measured_stress,
                    "relative_error": {"displacement": displacement_error, "stress": stress_error},
                }
            )
        shell_pressure = _shell_pressure_smoke(
            operations, doc, patch, left_edge, registry
        )
        report = {
            "ok": True,
            "formulation": "membrane",
            "mesh_dimension": "2D",
            "expected": {"stress_pa": EXPECTED_STRESS_PA, "displacement_m": EXPECTED_DISPLACEMENT_M},
            "measured": {"stress_pa": measured_stress, "displacement_m": measured_displacement},
            "relative_error": {"stress": stress_error, "displacement": displacement_error},
            "tolerance": RELATIVE_TOLERANCE,
            "jobs": {
                "gmsh": {"state": gmsh_result["state"], "exit_code": gmsh_result.get("exit_code")},
                "calculix": {"state": calculix_result["state"], "exit_code": calculix_result.get("exit_code")},
            },
            "validation": {"valid": validation["valid"], "diagnostic_count": len(validation["diagnostics"])},
            "route_smoke": {"force": force_route["kind"], "shell_pressure": shell_pressure},
        }
        print(json.dumps(report, separators=(",", ":"), sort_keys=True))
        return report
    finally:
        App.closeDocument(doc.Name)
        setattr(App, guard_name, False)


# FreeCADCmd positional dispatch uses a filename-derived module name.
run_benchmark()
