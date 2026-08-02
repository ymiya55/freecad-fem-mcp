"""Optional FreeCADCmd smoke test for the native Addon vertical slice.

Run with the FreeCAD 1.1.3 Python/FreeCADCmd interpreter.  The script is kept
outside pytest's ``test_*.py`` discovery because it needs a real FreeCAD host,
Gmsh, CalculiX, and a Qt event loop.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


def _wait_job(registry, job_id: str, timeout: float = 60.0):
    deadline = time.time() + timeout
    previous = None
    while time.time() < deadline:
        current = registry.get(job_id)
        if current["state"] != previous:
            native = registry._jobs[job_id].process
            print(
                {
                    "job": job_id,
                    "state": current["state"],
                    "qprocess_state": str(native.state()),
                    "qprocess_error": native.errorString(),
                    "exit_code": native.exitCode(),
                },
                flush=True,
            )
            previous = current["state"]
        if current["state"] not in {"queued", "running"}:
            return current
        from PySide import QtCore  # type: ignore

        # FreeCADCmd has no continuously running GUI event loop. A bounded
        # QProcess wait pumps the native completion signal without blocking
        # the production Addon's asynchronous GUI path.
        native.waitForFinished(50)
        QtCore.QCoreApplication.processEvents()
        time.sleep(0.05)
    raise AssertionError({"timeout": timeout, "job": registry.get(job_id)})


def run() -> None:
    try:
        import FreeCAD as App  # type: ignore
        import ObjectsFem  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this smoke test with FreeCADCmd 1.1.3") from exc
    # Processing QProcess events during FreeCAD startup can cause the
    # positional script to be dispatched a second time. Guard the host,
    # rather than this Python module instance, against re-entry.
    if getattr(App, "_FreeCADFEMMCPIntegrationRunning", False):
        return
    App._FreeCADFEMMCPIntegrationRunning = True

    addon_root = Path(__file__).resolve().parents[1] / "addon"
    if str(addon_root) not in sys.path:
        sys.path.insert(0, str(addon_root))
    from FreeCADFEMMCP.jobs import QProcessJobRegistry
    from FreeCADFEMMCP.operations import FreeCADOperations

    doc = App.newDocument("FreeCADFEMMCPIntegration")
    try:
        box = doc.addObject("Part::Box", "Cantilever")
        box.Length, box.Width, box.Height = 100.0, 20.0, 20.0
        doc.recompute()
        operations = FreeCADOperations(app=App, objects_fem=ObjectsFem, allowed_roots=[str(Path.cwd())])
        analysis = operations.create_analysis("Analysis")
        operations.set_material(analysis["name"], {"youngs_modulus_pa": 210e9, "poisson_ratio": 0.3, "density_kg_m3": 7850.0})
        operations.add_constraint(analysis["name"], "fixed", {"references": [{"object": "Cantilever", "sub_element": "Face1"}]})
        operations.add_constraint(analysis["name"], "force", {"references": [{"object": "Cantilever", "sub_element": "Face6"}], "force": 1000.0, "direction": [0.0, 0.0, -1.0]})
        operations.add_constraint(analysis["name"], "pressure", {"references": [{"object": "Cantilever", "sub_element": "Face2"}], "pressure": 1000.0})
        mesh = operations.create_mesh(analysis["name"], "GmshMesh", shape="Cantilever", ElementOrder="1st", CharacteristicLengthMax=5.0)
        registry = QProcessJobRegistry()
        print("starting gmsh", flush=True)
        gmsh = registry.start_gmsh(doc.getObject(mesh["name"]))
        gmsh_result = _wait_job(registry, gmsh["id"])
        assert gmsh_result["state"] == "completed", gmsh_result
        validation = operations.validate(analysis["name"])
        assert validation["valid"], validation
        solver_id = analysis["solver"]
        print("starting calculix", flush=True)
        solver_job = registry.start_calculix(doc.getObject(solver_id))
        solver_result = _wait_job(registry, solver_job["id"])
        assert solver_result["state"] == "completed", solver_result
        solver = doc.getObject(solver_id)
        results = getattr(solver, "Results", None)
        assert results is not None
        from FreeCADFEMMCP.pipeline import FemPostPipeline
        summary = FemPostPipeline(app=App).query_native(results, None, 0, 1000)
        assert summary["type"] == "Fem::FemPostPipeline"
        assert summary["fields"], summary
        assert summary["extrema"]["count"] > 0, summary
        print({"analysis": analysis, "mesh": mesh, "gmsh": gmsh, "solver": solver_job, "results": summary})
    finally:
        App.closeDocument(doc.Name)


# FreeCADCmd executes a positional script under its filename-derived module
# name instead of ``__main__``.  This file is intentionally not a pytest module.
run()
