"""Minimal FreeCAD GUI workbench integration."""

from __future__ import annotations

try:
    import FreeCADGui as Gui  # type: ignore
except ImportError:  # protocol tests/imports outside FreeCAD
    Gui = None

try:
    from .Init import start_bridge, stop_bridge
except ImportError:  # FreeCAD executes InitGui.py with the addon on sys.path
    import sys
    from pathlib import Path
    import FreeCAD as App  # type: ignore

    addon_parent = str(Path(App.getUserAppDataDir()) / "Mod")
    if addon_parent not in sys.path:
        sys.path.insert(0, addon_parent)
    from FreeCADFEMMCP.Init import start_bridge, stop_bridge  # type: ignore


if Gui is not None:  # pragma: no cover - host GUI integration
    class FreeCADFEMMCPWorkbench(Gui.Workbench):
        MenuText = "FreeCAD FEM MCP"
        ToolTip = "Safe CalculiX/Gmsh FEM bridge"
        Icon = ""

        def Initialize(self) -> None:
            self.appendToolbar("FreeCAD FEM MCP", ["FreeCADFEMMCP_StartBridge", "FreeCADFEMMCP_StopBridge"])
            self.appendMenu("FreeCAD FEM MCP", ["FreeCADFEMMCP_StartBridge", "FreeCADFEMMCP_StopBridge"])

        def GetClassName(self) -> str:
            return "Gui::PythonWorkbench"

        def Activated(self) -> None:
            pass

        def Deactivated(self) -> None:
            pass

    class _StartBridge:
        def Activated(self) -> None:
            start_bridge()

        def GetResources(self):
            return {"MenuText": "Start FEM MCP bridge", "ToolTip": "Start localhost FEM bridge"}

    class _StopBridge:
        def Activated(self) -> None:
            stop_bridge()

        def GetResources(self):
            return {"MenuText": "Stop FEM MCP bridge", "ToolTip": "Stop localhost FEM bridge"}

    Gui.addCommand("FreeCADFEMMCP_StartBridge", _StartBridge())
    Gui.addCommand("FreeCADFEMMCP_StopBridge", _StopBridge())
    Gui.addWorkbench(FreeCADFEMMCPWorkbench())

    # Start automatically when the workbench is loaded.  A failed version
    # gate, missing configuration, or occupied port must not prevent FreeCAD's
    # GUI from starting; report only a generic warning (never credentials).
    try:
        start_bridge()
    except Exception:
        try:
            import FreeCAD as App  # type: ignore
            console = getattr(App, "Console", None)
            warning = getattr(console, "PrintWarning", None) if console is not None else None
            if callable(warning):
                warning("FreeCAD FEM MCP bridge could not start; use the Start Bridge command after checking configuration.\n")
        except Exception:
            pass
