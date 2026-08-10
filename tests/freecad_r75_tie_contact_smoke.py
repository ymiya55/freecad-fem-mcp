"""Portable FreeCAD 1.1.3 R7.5 tie/contact writer smoke.

The smoke uses native Addon operations and the verified CalculiX writer
functions.  It does not inject an input deck or invoke a legacy solver.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any


def _references(obj: Any) -> list[tuple[str, list[str]]]:
    result = []
    for target, subelements in getattr(obj, "References", []) or []:
        if isinstance(subelements, str):
            subelements = [subelements]
        result.append((str(getattr(target, "Name", "")), list(subelements or [])))
    return result


def run() -> None:
    try:
        import FreeCAD as app  # type: ignore
        import ObjectsFem  # type: ignore
        import Part  # type: ignore
        import femsolver.calculix.write_constraint_contact as contact_writer  # type: ignore
        import femsolver.calculix.write_constraint_tie as tie_writer  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this smoke with FreeCADCmd 1.1.3") from exc
    if getattr(app, "_R7TieContactSmokeRunning", False):
        return
    app._R7TieContactSmokeRunning = True
    script_path = Path(globals().get("__file__", Path.cwd() / "tests" / "freecad_r75_tie_contact_smoke.py"))
    addon = script_path.resolve().parents[1] / "addon"
    sys.path.insert(0, str(addon))
    from FreeCADFEMMCP.operations import FreeCADOperations  # type: ignore

    doc = app.newDocument("R7TieContactSmoke")
    try:
        patch = doc.addObject("Part::Feature", "ShellPair")
        patch.Shape = Part.makeCompound(
            [
                Part.makePlane(10, 5, app.Vector(0, 0, 0)),
                Part.makePlane(10, 5, app.Vector(0, 6, 0)),
            ]
        )
        operations = FreeCADOperations(app=app, objects_fem=ObjectsFem)
        analysis = operations.create_analysis("ConnectionAnalysis", "static")
        operations.assign_element_geometry(
            analysis["name"],
            "shell",
            {
                "name": "ShellPairGeometry",
                "references": [{"object": "ShellPair", "sub_element": "Face1"}],
                "thickness_m": 0.001,
            },
        )
        tie = operations.add_connection(
            analysis["name"],
            "tie",
            {
                "references": [
                    {"object": "ShellPair", "sub_element": "Face1"},
                    {"object": "ShellPair", "sub_element": "Face2"},
                ],
                "tolerance_m": 0.001,
                "adjust": True,
            },
        )
        contact = operations.add_connection(
            analysis["name"],
            "contact",
            {
                "references": [
                    {"object": "ShellPair", "sub_element": "Face1"},
                    {"object": "ShellPair", "sub_element": "Face2"},
                ],
                "surface_behavior": "hard",
            },
        )
        tie_obj = doc.getObject(tie["name"])
        contact_obj = doc.getObject(contact["name"])
        expected_refs = [("ShellPair", ["Face1", "Face2"])]
        assert _references(tie_obj) == expected_refs
        assert _references(contact_obj) == expected_refs
        tie_data = {
            "TieSlaveFaces": [(None, [1], False)],
            "TieMasterFaces": [(None, [2], False)],
        }
        stream = io.StringIO()
        tie_writer.write_meshdata_constraint(stream, tie_data, tie_obj, None)
        tie_writer.write_constraint(stream, tie_data, tie_obj, None)
        tie_text = stream.getvalue()
        assert "*TIE" in tie_text and "TIE_DEP" in tie_text and "TIE_IND" in tie_text
        contact_data = {
            "ContactSlaveFaces": [(None, [3], False)],
            "ContactMasterFaces": [(None, [4], False)],
        }
        stream = io.StringIO()
        contact_writer.write_meshdata_constraint(stream, contact_data, contact_obj, None)
        contact_writer.write_constraint(stream, contact_data, contact_obj, None)
        contact_text = stream.getvalue()
        assert "*CONTACT PAIR" in contact_text and "PRESSURE-OVERCLOSURE=HARD" in contact_text
        print(
            json.dumps(
                {
                    "tie": {"references": _references(tie_obj), "writer": tie_text},
                    "contact": {"references": _references(contact_obj), "writer": contact_text},
                },
                sort_keys=True,
            )
        )
    finally:
        app.closeDocument(doc.Name)


run()
