"""FreeCAD Addon entry point.

Importing this module outside FreeCAD is harmless.  Inside a supported host it
exposes ``start_bridge``/``stop_bridge`` for InitGui and scripted clients.
"""

from __future__ import annotations

from typing import Any, Optional

_bridge: Optional[Any] = None
_service: Optional[Any] = None


def _load_components():
    """Import FEM-dependent modules only after FreeCAD's GUI is ready."""
    try:
        from .bridge import BridgeConfig, LocalhostBridge
        from .operations import FreeCADOperations
        from .service import FEMService
        from .version import host_version
    except ImportError:  # FreeCAD may execute Init.py outside package context
        import sys
        from pathlib import Path

        import FreeCAD as App  # type: ignore

        addon_parent = str(Path(App.getUserAppDataDir()) / "Mod")
        if addon_parent not in sys.path:
            sys.path.insert(0, addon_parent)
        from FreeCADFEMMCP.bridge import BridgeConfig, LocalhostBridge  # type: ignore
        from FreeCADFEMMCP.operations import FreeCADOperations  # type: ignore
        from FreeCADFEMMCP.service import FEMService  # type: ignore
        from FreeCADFEMMCP.version import host_version  # type: ignore

    return BridgeConfig, LocalhostBridge, FEMService, FreeCADOperations, host_version


def start_bridge(config: Optional[Any] = None) -> Any:
    global _bridge, _service
    if _bridge is not None and _bridge.address is not None:
        return _bridge
    BridgeConfig, LocalhostBridge, FEMService, FreeCADOperations, host_version = _load_components()
    # Gate before opening a socket, so unsupported FreeCAD releases do not
    # expose a partially working endpoint.
    try:
        host_version()
    except RuntimeError:
        # A plain Python import is useful for protocol tests; no host means no
        # bridge is started until FreeCAD calls this function.
        raise
    bridge_config = config or BridgeConfig()
    roots = bridge_config.allowed_roots or None
    _service = FEMService(operations=FreeCADOperations(allowed_roots=roots))
    _bridge = LocalhostBridge(_service, bridge_config)
    _bridge.start()
    return _bridge


def stop_bridge() -> None:
    global _bridge, _service
    if _bridge is not None:
        _bridge.stop()
    _bridge, _service = None, None
