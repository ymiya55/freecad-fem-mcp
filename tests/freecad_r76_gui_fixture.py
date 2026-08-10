"""Generate a small named beam/shell FCStd fixture for GUI acceptance.

The document contains geometry only.  Analyses, meshes, materials, and
constraints are intentionally created later through the MCP public routes.
The output path is explicit (``--output``) or defaults to a workspace-local
file, refuses overwrite, and is never emitted as an absolute path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _output_path(script_path: Path) -> tuple[Path, Path]:
    workspace = script_path.resolve().parents[1]
    arguments = list(sys.argv[1:])
    output_value: str | None = None
    if "--output" in arguments:
        index = arguments.index("--output")
        if index + 1 >= len(arguments):
            raise SystemExit("--output requires a path")
        output_value = arguments[index + 1]
    elif arguments and not arguments[0].startswith("-"):
        output_value = arguments[0]
    target = Path(output_value) if output_value else workspace / "r76_gui_fixture.FCStd"
    if not target.is_absolute():
        target = workspace / target
    target = target.resolve()
    try:
        target.relative_to(workspace)
    except ValueError as exc:
        raise SystemExit("output must remain inside the workspace") from exc
    if target.suffix.lower() != ".fcstd":
        raise SystemExit("output must have .FCStd suffix")
    if target.exists():
        raise SystemExit("refusing to overwrite an existing FCStd")
    return workspace, target


def run() -> dict[str, Any]:
    try:
        import FreeCAD as app  # type: ignore
        import Part  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this fixture generator with FreeCADCmd 1.1.3") from exc
    if getattr(app, "_R7GuiFixtureRunning", False):
        return {"ok": True, "reentered": True}
    app._R7GuiFixtureRunning = True
    script_path = Path(
        globals().get("__file__", Path.cwd() / "tests" / "freecad_r76_gui_fixture.py")
    )
    workspace, target = _output_path(script_path)
    doc = app.newDocument("R76GuiFixture")
    try:
        beam = doc.addObject("Part::Feature", "BeamFixtureLine")
        beam.Label = "Beam fixture line (Edge1)"
        beam.Shape = Part.makeLine(
            app.Vector(0.0, 0.0, 0.0), app.Vector(1000.0, 0.0, 0.0)
        )
        shell = doc.addObject("Part::Feature", "ShellFixtureFace")
        shell.Label = "Shell fixture rectangle (Face1)"
        shell.Shape = Part.makePlane(1000.0, 500.0, app.Vector(0.0, 0.0, 0.0))
        doc.recompute()
        if beam.Shape.isNull() or shell.Shape.isNull():
            raise SystemExit("fixture geometry is null")
        if beam.Shape.getElement("Edge1").ShapeType != "Edge":
            raise SystemExit("fixture beam is not Edge1")
        if shell.Shape.getElement("Face1").ShapeType != "Face":
            raise SystemExit("fixture shell is not Face1")
        doc.saveAs(str(target))
        report = {
            "ok": True,
            "output": target.relative_to(workspace).as_posix(),
            "beam": {"object": beam.Name, "sub_element": "Edge1"},
            "shell": {"object": shell.Name, "sub_element": "Face1"},
            "analysis_objects": False,
        }
        print(json.dumps(report, separators=(",", ":"), sort_keys=True))
        return report
    finally:
        app.closeDocument(doc.Name)
        app._R7GuiFixtureRunning = False


run()
