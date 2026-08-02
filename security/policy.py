"""Strict, dependency-free security boundary helpers.

These helpers are intentionally useful on Windows (the supported FreeCAD
platform) and on POSIX hosts used by CI.  They reject ambiguous path syntax
before normalisation, cap NDJSON input before parsing, and require an explicit
loopback host.  A caller should translate the exceptions into its protocol's
error response rather than exposing a traceback to a client.
"""

from __future__ import annotations

import ipaddress
import json
import ntpath
import os
import re
import stat
from pathlib import Path
from typing import Any, Iterable, Iterator, Union


class SecurityPolicyError(ValueError):
    """Base class for values rejected at a security boundary."""


class NDJSONError(SecurityPolicyError):
    """A line in an NDJSON request is malformed or violates a limit."""


class DuplicateKeyError(NDJSONError):
    """A JSON object contained a duplicate key."""


class PathPolicyError(SecurityPolicyError):
    """A path is absolute, escapes its root, or traverses a reparse point."""


def is_loopback_host(host: object) -> bool:
    """Return ``True`` only for an explicit loopback address or ``localhost``.

    DNS names other than ``localhost`` are rejected.  In particular, an empty
    host, wildcard addresses (``0.0.0.0``/``::``), and hostnames that merely
    resolve to loopback are not accepted; resolving names at a security
    boundary is vulnerable to DNS rebinding and configuration drift.
    """

    if not isinstance(host, str):
        return False
    value = host.strip().lower().rstrip(".")
    if value == "localhost":
        return True
    # URL-style bracketed IPv6 literals are common in configuration files.
    if len(value) > 2 and value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _duplicate_key_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    # JSON permits neither NaN nor Infinity.  json.loads accepts them by
    # default for JavaScript compatibility, so reject them explicitly.
    raise NDJSONError(f"non-standard JSON constant: {value}")


def _line_bytes(line: Union[str, bytes, bytearray, memoryview]) -> bytes:
    if isinstance(line, str):
        return line.encode("utf-8")
    if isinstance(line, (bytes, bytearray, memoryview)):
        return bytes(line)
    raise NDJSONError(f"NDJSON input yielded {type(line).__name__}, expected text or bytes")


def _iter_lines(data: Union[str, bytes, bytearray, memoryview, Iterable[Union[str, bytes]]]) -> Iterator[bytes]:
    if isinstance(data, str):
        yield from (part.encode("utf-8") for part in data.splitlines(keepends=True))
        # ``splitlines`` returns no item for an empty string and omits a final
        # empty line; both cases are equivalent to no additional NDJSON value.
        return
    if isinstance(data, (bytes, bytearray, memoryview)):
        raw = bytes(data)
        yield from raw.splitlines(keepends=True)
        return
    for line in data:
        yield _line_bytes(line)


def parse_ndjson(
    data: Union[str, bytes, bytearray, memoryview, Iterable[Union[str, bytes]]],
    *,
    max_line_bytes: int = 1 * 1024 * 1024,
    max_total_bytes: int = 8 * 1024 * 1024,
    allow_blank_lines: bool = True,
) -> list[dict[str, Any]]:
    """Parse bounded newline-delimited JSON objects with duplicate-key checks.

    ``data`` may be a text/bytes buffer or an iterable of complete lines (for
    example a file opened in binary mode).  The limits include newline bytes.
    Every non-blank line must decode as UTF-8 and contain a JSON object.  A
    :class:`NDJSONError` is raised for malformed input, duplicate keys,
    non-object values, non-finite numbers, or size-limit violations.
    """

    if not isinstance(max_line_bytes, int) or max_line_bytes < 1:
        raise ValueError("max_line_bytes must be a positive integer")
    if not isinstance(max_total_bytes, int) or max_total_bytes < 1:
        raise ValueError("max_total_bytes must be a positive integer")

    records: list[dict[str, Any]] = []
    total = 0
    for number, raw_line in enumerate(_iter_lines(data), start=1):
        total += len(raw_line)
        if total > max_total_bytes:
            raise NDJSONError(f"NDJSON input exceeds {max_total_bytes} bytes")
        if len(raw_line) > max_line_bytes:
            raise NDJSONError(f"NDJSON line {number} exceeds {max_line_bytes} bytes")
        payload = raw_line.rstrip(b"\r\n")
        if not payload.strip():
            if allow_blank_lines:
                continue
            raise NDJSONError(f"blank NDJSON line {number} is not allowed")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NDJSONError(f"line {number} is not valid UTF-8") from exc
        try:
            value = json.loads(
                text,
                object_pairs_hook=_duplicate_key_object,
                parse_constant=_reject_json_constant,
            )
        except DuplicateKeyError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise NDJSONError(f"malformed JSON on line {number}") from exc
        if not isinstance(value, dict):
            raise NDJSONError(f"line {number} must contain a JSON object")
        records.append(value)
    return records


_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def _looks_absolute_or_device(raw: str) -> bool:
    """Recognise Windows absolute, UNC, and device path spellings anywhere."""

    # Convert forward slashes so ``//server/share`` and mixed separators are
    # treated exactly like their Windows counterparts.
    win = raw.replace("/", "\\")
    return bool(
        _DRIVE_PREFIX.match(win)
        or win.startswith("\\")  # rooted and UNC paths
        or win.startswith("\\\\?\\")
        or win.startswith("\\\\.\\")
        or ntpath.isabs(win)
    )


def _has_parent_component(raw: str) -> bool:
    components = re.split(r"[\\/]+", raw)
    return any(component == ".." for component in components)


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = os.stat(path, follow_symlinks=False).st_file_attributes
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _ensure_no_reparse_components(base: Path, relative: str) -> None:
    """Reject symlinks/junctions in an existing path below ``base``."""

    current = base
    for component in re.split(r"[\\/]+", relative):
        if not component or component == ".":
            continue
        current = current / component
        if current.exists() and _is_reparse_point(current):
            raise PathPolicyError(f"reparse point is not allowed: {current}")


def safe_join(base_dir: Union[str, os.PathLike[str]], relative_path: Union[str, os.PathLike[str]]) -> Path:
    """Resolve a user path below ``base_dir`` under a strict path policy.

    Absolute paths, drive-qualified paths, UNC/device paths, NUL bytes, and
    parent components are rejected before joining.  Existing symlink/junction
    components are rejected to prevent a time-of-check/time-of-use escape.
    The returned path may not exist yet, which is useful for controlled file
    creation inside a sandbox.
    """

    try:
        raw_obj = os.fspath(relative_path)
        base_obj = os.fspath(base_dir)
    except TypeError as exc:
        raise PathPolicyError("base_dir and relative_path must be path-like") from exc
    if isinstance(raw_obj, bytes):
        try:
            raw = raw_obj.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PathPolicyError("path is not valid UTF-8") from exc
    else:
        raw = str(raw_obj)
    base = Path(base_obj).expanduser().resolve(strict=False)
    if "\x00" in raw:
        raise PathPolicyError("NUL bytes are not allowed in paths")
    if not raw or raw.strip() in {".", ""}:
        # An empty path is harmless but ambiguous at API boundaries.  Treat
        # it as the root itself only when callers explicitly pass '.'.
        if raw != ".":
            raise PathPolicyError("empty path is not allowed")
    if _looks_absolute_or_device(raw):
        raise PathPolicyError(f"absolute, UNC, or device path is not allowed: {raw!r}")
    if _has_parent_component(raw):
        raise PathPolicyError("parent path components are not allowed")
    _ensure_no_reparse_components(base, raw)

    candidate = (base / Path(raw)).resolve(strict=False)
    try:
        common = os.path.commonpath((os.path.normcase(str(base)), os.path.normcase(str(candidate))))
    except ValueError as exc:
        raise PathPolicyError("path is on a different volume") from exc
    if common != os.path.normcase(str(base)):
        raise PathPolicyError("path escapes its base directory")
    return candidate


def require_loopback_host(host: object) -> str:
    """Validate and return a host string, raising a policy error otherwise."""

    if not is_loopback_host(host):
        raise SecurityPolicyError("only explicit loopback hosts are allowed")
    return str(host)


__all__ = [
    "DuplicateKeyError",
    "NDJSONError",
    "PathPolicyError",
    "SecurityPolicyError",
    "is_loopback_host",
    "parse_ndjson",
    "require_loopback_host",
    "safe_join",
]
