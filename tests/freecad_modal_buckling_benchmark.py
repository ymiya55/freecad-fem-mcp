"""Native FreeCAD 1.1.3 R2 frequency/buckling acceptance benchmarks.

Run this executable benchmark with the installed FreeCAD command line host::

    FreeCADCmd.exe tests/freecad_modal_buckling_benchmark.py

Both cases use only FreeCAD's native ``SolverCalculiX``/Gmsh tools and the
native result importer.  No legacy solver, hand-written CalculiX input, or
result-file parser is used.  The geometry is built in millimetres (FreeCAD's
solid FEM convention), material values are given in SI units at the addon
boundary, and the reference equations below are evaluated in SI units.

The frequency case is a 100 mm long, 10 mm square cantilever.  Its first
Euler--Bernoulli bending frequency is

    f1 = beta1**2/(2*pi*L**2) * sqrt(E*I/(rho*A)), beta1 = 1.8751040687

The buckling case is the same fixed-free column with a 1,000 N axial
compression.  The first Euler load and the expected CalculiX load multiplier
are

    Pcr = pi**2*E*I/(4*L**2), factor = Pcr/Papplied

The second-order tetrahedral mesh is deliberately explicit.  Acceptance
thresholds are relative errors (5 percent for each quantity), and every
native result is checked for a corresponding non-empty mode block before a
bounded value is extracted from the native ``CalculiXOutput`` document.
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable


LENGTH_MM = 100.0
WIDTH_MM = 10.0
HEIGHT_MM = 10.0
LENGTH_M = LENGTH_MM / 1000.0
WIDTH_M = WIDTH_MM / 1000.0
HEIGHT_M = HEIGHT_MM / 1000.0
AREA_M2 = WIDTH_M * HEIGHT_M
INERTIA_M4 = WIDTH_M * HEIGHT_M**3 / 12.0
YOUNGS_MODULUS_PA = 210.0e9
POISSON_RATIO = 0.3
DENSITY_KG_M3 = 7850.0
APPLIED_COMPRESSION_N = 1000.0
BETA1 = 1.875104068711961
MESH_SIZE_MM = 5.0
MODE_COUNT = 1
RELATIVE_TOLERANCE = 0.05
JOB_TIMEOUT_S = 600.0

EULER_FREQUENCY_HZ = (
    BETA1**2
    / (2.0 * math.pi * LENGTH_M**2)
    * math.sqrt(YOUNGS_MODULUS_PA * INERTIA_M4 / (DENSITY_KG_M3 * AREA_M2))
)
EULER_BUCKLING_LOAD_N = (
    math.pi**2 * YOUNGS_MODULUS_PA * INERTIA_M4 / (4.0 * LENGTH_M**2)
)
EULER_BUCKLING_FACTOR = EULER_BUCKLING_LOAD_N / APPLIED_COMPRESSION_N


_FLOAT_TOKEN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
_FREQUENCY_ROW = re.compile(
    r"^\s*(\d+)\s+("
    + _FLOAT_TOKEN
    + r")\s+("
    + _FLOAT_TOKEN
    + r")\s+("
    + _FLOAT_TOKEN
    + r")\s+("
    + _FLOAT_TOKEN
    + r")\s*$"
)
_BUCKLING_ROW = re.compile(
    r"^\s*(\d+)\s+(" + _FLOAT_TOKEN + r")\s*$"
)


def _finite(value: Any, label: str) -> float:
    """Convert one native scalar while rejecting malformed/non-finite data."""

    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AssertionError("{} is not numeric".format(label)) from exc
    if not math.isfinite(converted):
        raise AssertionError("{} is not finite".format(label))
    return converted


def _wait_job(registry: Any, job_id: str, timeout_s: float = JOB_TIMEOUT_S) -> dict[str, Any]:
    """Pump native QProcess completion without requiring a GUI event loop."""

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        registry.wait(job_id, 100)
        summary = registry.get(job_id)
        if summary["state"] not in {"queued", "running"}:
            return summary
        try:
            from PySide import QtCore  # type: ignore

            QtCore.QCoreApplication.processEvents()
        except ImportError:
            pass
        time.sleep(0.02)
    raise AssertionError("job {} did not finish within {} seconds".format(job_id, timeout_s))


def _face_at_x(shape: Any, x_target: float) -> str:
    """Return a stable box face name from its centre-of-mass coordinate."""

    faces = list(getattr(shape, "Faces", []) or [])
    if not faces:
        raise AssertionError("benchmark solid has no faces")
    selected = min(
        enumerate(faces, 1),
        key=lambda item: abs(_finite(getattr(item[1].CenterOfMass, "x", None), "face x") - x_target),
    )
    return "Face{}".format(selected[0])


def _native_pipeline(results: Any) -> Any:
    """Select the exact native FemPostPipeline result object."""

    values = results if isinstance(results, (list, tuple)) else [results]
    for value in values:
        if getattr(value, "TypeId", "") == "Fem::FemPostPipeline":
            return value
    raise AssertionError("solver.Results did not contain a native FemPostPipeline")


def _vtk_blocks(data: Any) -> Iterable[Any]:
    """Yield bounded leaf blocks from the native VTK multiblock dataset."""

    if data is None:
        return
    get_count = getattr(data, "GetNumberOfBlocks", None)
    get_block = getattr(data, "GetBlock", None)
    if callable(get_count) and callable(get_block):
        try:
            count = min(max(int(get_count()), 0), 128)
        except (TypeError, ValueError, RuntimeError):
            count = 0
        for index in range(count):
            try:
                block = get_block(index)
            except (AttributeError, IndexError, RuntimeError, TypeError):
                block = None
            if block is not None:
                yield from _vtk_blocks(block)
        return
    yield data


def _has_displacement_block(pipeline: Any, mode: int, block_offset: int = 0) -> int:
    """Prove that the requested mode has imported native displacement data."""

    if not isinstance(mode, int) or mode < 1 or mode > 100:
        raise AssertionError("mode number is outside the safe range")
    if not isinstance(block_offset, int) or block_offset < 0 or block_offset > 100:
        raise AssertionError("native mode block offset is outside the safe range")
    blocks = list(_vtk_blocks(getattr(pipeline, "Data", None)))
    block_index = mode - 1 + block_offset
    if len(blocks) <= block_index:
        raise AssertionError("native result has no imported block for mode {}".format(mode))
    block = blocks[block_index]
    points = getattr(block, "GetPoints", lambda: None)()
    if points is None:
        raise AssertionError("native mode {} has no points".format(mode))
    try:
        point_count = int(points.GetNumberOfPoints())
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise AssertionError("native mode {} point count is unavailable".format(mode)) from exc
    if not 1 <= point_count <= 200000:
        raise AssertionError("native mode {} point count is invalid".format(mode))
    point_data = getattr(block, "GetPointData", lambda: None)()
    if point_data is None:
        raise AssertionError("native mode {} has no point data".format(mode))
    count_getter = getattr(point_data, "GetNumberOfArrays", None)
    array_getter = getattr(point_data, "GetArray", None)
    if not callable(count_getter) or not callable(array_getter):
        raise AssertionError("native mode {} arrays are unavailable".format(mode))
    try:
        array_count = min(max(int(count_getter()), 0), 512)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise AssertionError("native mode {} array count is invalid".format(mode)) from exc
    for index in range(array_count):
        try:
            array = array_getter(index)
            name_getter = getattr(array, "GetName", None)
            name = str(name_getter() if callable(name_getter) else "")
            tuples_getter = getattr(array, "GetNumberOfTuples", None)
            tuples = int(tuples_getter()) if callable(tuples_getter) else 0
        except (AttributeError, TypeError, ValueError, RuntimeError):
            continue
        if "displacement" in "".join(ch.lower() for ch in name if ch.isalnum()) and tuples == point_count:
            return block_index
    raise AssertionError("native mode {} has no imported displacement array".format(mode))


def _native_text(results: Any) -> str:
    """Return the bounded text object shipped alongside a native pipeline."""

    values = results if isinstance(results, (list, tuple)) else [results]
    for value in values:
        if getattr(value, "TypeId", "") != "App::TextDocument":
            continue
        text = getattr(value, "Text", None)
        if isinstance(text, str) and 0 < len(text) <= 4 * 1024 * 1024:
            return text
    raise AssertionError("native solver result did not include bounded CalculiX output text")


def _native_frame_frequency(pipeline: Any, mode: int) -> float:
    """Read the native Frame enum entry corresponding to one mode block.

    FreeCAD 1.1.3 exposes one rounded-Hz Frame enum value per frequency block;
    the native text document is still used for the full-precision value.  The
    two values are cross-checked by ``_extract_mode_frequency_hz`` below.
    """

    enumerator = getattr(pipeline, "getEnumerationsOfProperty", None)
    if not callable(enumerator):
        raise AssertionError("native frequency pipeline has no Frame enumeration")
    try:
        values = list(enumerator("Frame") or [])[:100]
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        raise AssertionError("native frequency Frame enumeration is unavailable") from exc
    if len(values) < mode:
        raise AssertionError("native frequency Frame enumeration has no mode {}".format(mode))
    frame_frequency = _finite(values[mode - 1], "native Frame frequency")
    if frame_frequency <= 0.0:
        raise AssertionError("native Frame frequency is not positive")
    return frame_frequency


def _compact(text: str) -> str:
    return "".join(character for character in text.upper() if character.isalpha())


def _extract_mode_frequency_hz(results: Any, mode: int = 1) -> dict[str, Any]:
    """Extract one mode frequency from native blocks + native output text."""

    pipeline = _native_pipeline(results)
    block_index = _has_displacement_block(pipeline, mode)
    text = _native_text(results)
    active = False
    for line in text.splitlines():
        compact = _compact(line)
        if "EIGENVALUEOUTPUT" in compact:
            active = True
            continue
        if active and "PARTICIPATION" in compact:
            break
        if not active:
            continue
        match = _FREQUENCY_ROW.match(line)
        if match is None or int(match.group(1)) != mode:
            continue
        # CalculiX columns are mode, eigenvalue, radians/time, cycles/time,
        # imaginary radians/time.  The fourth token is therefore Hz for a
        # unit-second structural model.
        frequency_hz = _finite(match.group(4), "mode frequency")
        if frequency_hz <= 0.0:
            raise AssertionError("mode frequency is not positive")
        frame_frequency = _native_frame_frequency(pipeline, mode)
        if abs(frame_frequency - frequency_hz) > 0.1:
            raise AssertionError("native Frame frequency does not match mode {}".format(mode))
        return {
            "mode": mode,
            "frequency_hz": frequency_hz,
            "frame_frequency_hz": frame_frequency,
            "block_index": block_index,
        }
    raise AssertionError("native output has no frequency row for mode {}".format(mode))


def _extract_buckling_factor(results: Any, mode: int = 1) -> dict[str, Any]:
    """Extract one buckling factor from native blocks + native output text."""

    pipeline = _native_pipeline(results)
    # CalculiX imports one static/preload block before the buckling mode
    # blocks.  Thus mode 1 is Data block 1 and Frame enum entry 1 (entry 0 is
    # the preload frame ``0.00``).
    block_index = _has_displacement_block(pipeline, mode, block_offset=1)
    text = _native_text(results)
    active = False
    for line in text.splitlines():
        compact = _compact(line)
        if "BUCKLINGFACTOROUTPUT" in compact:
            active = True
            continue
        if active and "EIGENVALUENUMBER" in compact:
            break
        if not active:
            continue
        match = _BUCKLING_ROW.match(line)
        if match is None or int(match.group(1)) != mode:
            continue
        factor = _finite(match.group(2), "buckling factor")
        if factor <= 0.0:
            raise AssertionError("buckling factor is not positive")
        enumerator = getattr(pipeline, "getEnumerationsOfProperty", None)
        if not callable(enumerator):
            raise AssertionError("native buckling pipeline has no Frame enumeration")
        try:
            frames = list(enumerator("Frame") or [])[:100]
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            raise AssertionError("native buckling Frame enumeration is unavailable") from exc
        if len(frames) <= mode:
            raise AssertionError("native buckling Frame enumeration has no mode {}".format(mode))
        frame_factor = _finite(frames[mode], "native Frame buckling factor")
        if frame_factor <= 0.0 or abs(frame_factor - factor) > 0.1:
            raise AssertionError("native Frame factor does not match mode {}".format(mode))
        return {
            "mode": mode,
            "buckling_factor": factor,
            "frame_factor": frame_factor,
            "block_index": block_index,
        }
    raise AssertionError("native output has no buckling row for mode {}".format(mode))


def _run_frequency(App: Any, ObjectsFem: Any, operations_cls: Any, registry_cls: Any) -> dict[str, Any]:
    doc = App.newDocument("R2CantileverFrequency")
    try:
        beam = doc.addObject("Part::Box", "CantileverBeam")
        beam.Length, beam.Width, beam.Height = LENGTH_MM, WIDTH_MM, HEIGHT_MM
        doc.recompute()
        operations = operations_cls(
            app=App,
            objects_fem=ObjectsFem,
            allowed_roots=[str(Path.cwd())],
        )
        analysis = operations.create_analysis(
            "FrequencyAnalysis",
            "frequency",
            eigenmodes_count=MODE_COUNT,
        )
        operations.set_material(
            analysis["name"],
            {
                "youngs_modulus_pa": YOUNGS_MODULUS_PA,
                "poisson_ratio": POISSON_RATIO,
                "density_kg_m3": DENSITY_KG_M3,
            },
        )
        operations.add_constraint(
            analysis["name"],
            "fixed",
            {"references": [{"object": "CantileverBeam", "sub_element": _face_at_x(beam.Shape, 0.0)}]},
        )
        mesh = operations.create_mesh(
            analysis["name"],
            "FrequencyMesh",
            shape="CantileverBeam",
            ElementOrder="2nd",
            CharacteristicLengthMax=MESH_SIZE_MM,
            CharacteristicLengthMin=MESH_SIZE_MM,
        )
        registry = registry_cls()
        gmsh = _wait_job(registry, registry.start_gmsh(doc.getObject(mesh["name"]))["id"])
        if gmsh["state"] != "completed":
            raise AssertionError("native Gmsh job failed: {}".format(gmsh["state"]))
        validation = operations.validate(analysis["name"])
        solver_job = _wait_job(
            registry,
            registry.start_calculix(doc.getObject(analysis["solver"]))["id"],
        )
        if solver_job["state"] != "completed":
            raise AssertionError("native CalculiX frequency job failed: {}".format(solver_job["state"]))
        solver = doc.getObject(analysis["solver"])
        extracted = _extract_mode_frequency_hz(solver.Results, MODE_COUNT)
        relative_error = abs(extracted["frequency_hz"] - EULER_FREQUENCY_HZ) / EULER_FREQUENCY_HZ
        if relative_error > RELATIVE_TOLERANCE:
            raise AssertionError(
                "frequency relative error {:.6g} exceeds {:.6g}".format(
                    relative_error, RELATIVE_TOLERANCE
                )
            )
        return {
            "geometry": {
                "length_mm": LENGTH_MM,
                "width_mm": WIDTH_MM,
                "height_mm": HEIGHT_MM,
                "mesh_element_order": "2nd",
                "mesh_size_mm": MESH_SIZE_MM,
                "boundary": "fixed-free cantilever at x=0 mm",
            },
            "material": {
                "youngs_modulus_pa": YOUNGS_MODULUS_PA,
                "poisson_ratio": POISSON_RATIO,
                "density_kg_m3": DENSITY_KG_M3,
            },
            "theory": {
                "equation": "beta1^2/(2*pi*L^2)*sqrt(E*I/(rho*A))",
                "beta1": BETA1,
                "frequency_hz": EULER_FREQUENCY_HZ,
            },
            "measured": extracted,
            "relative_error": relative_error,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "validation": validation,
            "jobs": {"gmsh": gmsh["state"], "calculix": solver_job["state"]},
        }
    finally:
        App.closeDocument(doc.Name)


def _run_buckling(App: Any, ObjectsFem: Any, operations_cls: Any, registry_cls: Any) -> dict[str, Any]:
    doc = App.newDocument("R2EulerColumnBuckling")
    try:
        column = doc.addObject("Part::Box", "EulerColumn")
        column.Length, column.Width, column.Height = LENGTH_MM, WIDTH_MM, HEIGHT_MM
        doc.recompute()
        operations = operations_cls(
            app=App,
            objects_fem=ObjectsFem,
            allowed_roots=[str(Path.cwd())],
        )
        analysis = operations.create_analysis(
            "BucklingAnalysis",
            "buckling",
            buckling_factors=MODE_COUNT,
            buckling_accuracy=0.01,
        )
        operations.set_material(
            analysis["name"],
            {
                "youngs_modulus_pa": YOUNGS_MODULUS_PA,
                "poisson_ratio": POISSON_RATIO,
                "density_kg_m3": DENSITY_KG_M3,
            },
        )
        operations.add_constraint(
            analysis["name"],
            "fixed",
            {"references": [{"object": "EulerColumn", "sub_element": _face_at_x(column.Shape, 0.0)}]},
        )
        operations.add_constraint(
            analysis["name"],
            "force",
            {
                "references": [{"object": "EulerColumn", "sub_element": _face_at_x(column.Shape, LENGTH_MM)}],
                "force": -APPLIED_COMPRESSION_N,
                "direction": [1.0, 0.0, 0.0],
            },
        )
        mesh = operations.create_mesh(
            analysis["name"],
            "BucklingMesh",
            shape="EulerColumn",
            ElementOrder="2nd",
            CharacteristicLengthMax=MESH_SIZE_MM,
            CharacteristicLengthMin=MESH_SIZE_MM,
        )
        registry = registry_cls()
        gmsh = _wait_job(registry, registry.start_gmsh(doc.getObject(mesh["name"]))["id"])
        if gmsh["state"] != "completed":
            raise AssertionError("native Gmsh job failed: {}".format(gmsh["state"]))
        validation = operations.validate(analysis["name"])
        solver_job = _wait_job(
            registry,
            registry.start_calculix(doc.getObject(analysis["solver"]))["id"],
        )
        if solver_job["state"] != "completed":
            raise AssertionError("native CalculiX buckling job failed: {}".format(solver_job["state"]))
        solver = doc.getObject(analysis["solver"])
        extracted = _extract_buckling_factor(solver.Results, MODE_COUNT)
        relative_error = abs(extracted["buckling_factor"] - EULER_BUCKLING_FACTOR) / EULER_BUCKLING_FACTOR
        if relative_error > RELATIVE_TOLERANCE:
            raise AssertionError(
                "buckling relative error {:.6g} exceeds {:.6g}".format(
                    relative_error, RELATIVE_TOLERANCE
                )
            )
        return {
            "geometry": {
                "length_mm": LENGTH_MM,
                "width_mm": WIDTH_MM,
                "height_mm": HEIGHT_MM,
                "mesh_element_order": "2nd",
                "mesh_size_mm": MESH_SIZE_MM,
                "boundary": "fixed-free column at x=0 mm",
            },
            "material": {
                "youngs_modulus_pa": YOUNGS_MODULUS_PA,
                "poisson_ratio": POISSON_RATIO,
                "density_kg_m3": DENSITY_KG_M3,
            },
            "load": {
                "type": "axial compression",
                "force_n": APPLIED_COMPRESSION_N,
                "direction": "-x at x=100 mm face",
            },
            "theory": {
                "equation": "pi^2*E*I/(4*L^2) for fixed-free Euler column",
                "critical_load_n": EULER_BUCKLING_LOAD_N,
                "expected_factor": EULER_BUCKLING_FACTOR,
            },
            "measured": extracted,
            "relative_error": relative_error,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "validation": validation,
            "jobs": {"gmsh": gmsh["state"], "calculix": solver_job["state"]},
        }
    finally:
        App.closeDocument(doc.Name)


def run_benchmark() -> dict[str, Any]:
    """Execute both native analyses and print a bounded JSON report."""

    try:
        import FreeCAD as App  # type: ignore
        import ObjectsFem  # type: ignore
    except ImportError as exc:
        raise RuntimeError("run with FreeCADCmd 1.1.3") from exc
    guard_name = "_FreeCADFEMMCPModalBucklingBenchmarkRunning"
    if getattr(App, guard_name, False):
        return {"status": "already_running"}
    setattr(App, guard_name, True)
    addon_root = Path(__file__).resolve().parents[1] / "addon"
    if str(addon_root) not in sys.path:
        sys.path.insert(0, str(addon_root))
    from FreeCADFEMMCP.jobs import QProcessJobRegistry
    from FreeCADFEMMCP.operations import FreeCADOperations

    try:
        report = {
            # FreeCADCmd sets sys.executable to the actual host path.  Do not
            # bake a developer-specific installation path into this public
            # benchmark; callers may invoke any FreeCAD 1.1.3 installation.
            "freecad_cmd": str(Path(sys.executable).resolve()),
            "freecad_cmd_exists": Path(sys.executable).is_file(),
            "freecad_version": str(App.Version()),
            "frequency": _run_frequency(App, ObjectsFem, FreeCADOperations, QProcessJobRegistry),
            "buckling": _run_buckling(App, ObjectsFem, FreeCADOperations, QProcessJobRegistry),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return report
    finally:
        setattr(App, guard_name, False)


if __name__ in {"__main__", Path(__file__).stem}:
    run_benchmark()
