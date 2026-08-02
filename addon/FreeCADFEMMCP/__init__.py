"""FreeCAD FEM MCP addon.

Keep package import deliberately lightweight.  FreeCAD executes ``Init.py``
before its GUI/FEM environment is fully initialised, so importing the native
operation graph here would make application startup order-dependent.
"""

from .version import ADDON_VERSION, SUPPORTED_MAX, SUPPORTED_MIN, check_version

__all__ = [
    "ADDON_VERSION", "SUPPORTED_MIN", "SUPPORTED_MAX", "check_version",
    "ALLOWED_METHODS", "BridgeError", "ProtocolError", "parse_request_line",
    "serialize_response", "StartupCredentials", "TokenAuthenticator",
    "BridgeConfig", "LocalhostBridge", "FEMService",
]


def __getattr__(name: str):
    """Lazily preserve the package-level API without importing FEM at startup."""
    if name in {"ALLOWED_METHODS", "BridgeError", "ProtocolError", "parse_request_line", "serialize_response"}:
        from . import protocol

        return getattr(protocol, name)
    if name in {"StartupCredentials", "TokenAuthenticator"}:
        from . import security

        return getattr(security, name)
    if name in {"BridgeConfig", "LocalhostBridge"}:
        from . import bridge

        return getattr(bridge, name)
    if name == "FEMService":
        from .service import FEMService

        return FEMService
    raise AttributeError(name)
