"""FreeCAD and addon version gates."""

from __future__ import annotations

import re
from typing import Any, Iterable, Tuple

ADDON_VERSION = "0.1.0"
SUPPORTED_MIN: Tuple[int, int, int] = (1, 1, 3)
SUPPORTED_MAX: Tuple[int, int, int] = (1, 2, 0)  # exclusive


class UnsupportedFreeCADVersion(RuntimeError):
    """Raised when the host FreeCAD version is outside our support range."""


def normalise_version(value: Any) -> Tuple[int, int, int]:
    if isinstance(value, (tuple, list)):
        pieces: Iterable[Any] = value
    elif isinstance(value, str):
        pieces = re.findall(r"\d+", value)
    else:
        try:
            pieces = list(value)
        except Exception as exc:
            raise ValueError("invalid FreeCAD version") from exc
    numbers = []
    for item in pieces:
        if len(numbers) == 3:
            break
        try:
            numbers.append(int(item))
        except (TypeError, ValueError):
            continue
    if not numbers:
        raise ValueError("invalid FreeCAD version")
    numbers.extend([0] * (3 - len(numbers)))
    return tuple(numbers[:3])  # type: ignore[return-value]


def is_supported(value: Any) -> bool:
    version = normalise_version(value)
    return SUPPORTED_MIN <= version < SUPPORTED_MAX


def check_version(value: Any) -> Tuple[int, int, int]:
    version = normalise_version(value)
    if not SUPPORTED_MIN <= version < SUPPORTED_MAX:
        raise UnsupportedFreeCADVersion(
            "FreeCAD {} is unsupported; require >=1.1.3 and <1.2".format(
                ".".join(str(part) for part in version)
            )
        )
    return version


def host_version(app: Any = None) -> Tuple[int, int, int]:
    if app is None:
        try:
            import FreeCAD as app  # type: ignore
        except ImportError as exc:
            raise RuntimeError("FreeCAD is not available") from exc
    getter = getattr(app, "Version", None)
    if getter is None:
        raise RuntimeError("FreeCAD.Version is unavailable")
    return check_version(getter() if callable(getter) else getter)
