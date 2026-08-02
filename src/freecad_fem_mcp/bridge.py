"""Authenticated, bounded NDJSON bridge client.

The MCP process has no direct FreeCAD, filesystem, shell, or Python-evaluation
capability.  It exchanges one JSON object per line with the companion Addon via a
small transport interface.  Tests can provide a fake transport implementing
``request``/``send_line``; production can use :class:`LocalNdjsonTransport`.
"""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
import itertools
import json
import math
import os
from pathlib import Path
import socket
import stat
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, runtime_checkable

BRIDGE_METHODS = frozenset(
    {
        "status",
        "document",
        "selection",
        "view",
        "capture",
        "open",
        "save",
        "analysis",
        "material",
        "constraint",
        "mesh",
        "validate",
        "jobs",
        "results",
    }
)
ALLOWED_METHODS = BRIDGE_METHODS

# A request is bounded before it reaches the transport.  This also avoids an
# accidental giant response being retained in the MCP process.
MAX_FRAME_BYTES = 1_048_576
MAX_METHOD_BYTES = 64
MAX_TOKEN_BYTES = 256
MAX_ERROR_BYTES = 1024
MAX_CONFIG_BYTES = 16 * 1024
ConnectionRecordStatus = Literal["missing", "invalid", "stale", "ready"]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-standard JSON number")


@dataclass(frozen=True, slots=True)
class ConnectionRecordDiagnostic:
    """Safe status for the local Addon connection record.

    The diagnostic deliberately contains no path, token, host, or port.  It can
    therefore be returned to an MCP caller without turning credentials or local
    filesystem details into an information leak.
    """

    status: ConnectionRecordStatus
    reason: str

    @property
    def state(self) -> ConnectionRecordStatus:
        """Alias used by callers that call the status a state."""

        return self.status

    @property
    def usable(self) -> bool:
        return self.status == "ready"


def _is_posix_pid_alive(pid: int) -> bool:
    """Check a PID with the POSIX signal-0 existence probe."""

    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False
    return True


def _is_windows_pid_alive(pid: int) -> bool:
    """Check a PID through read-only Windows process-query APIs.

    ``os.kill(pid, 0)`` is intentionally not used on Windows: Python maps
    ``os.kill`` to Windows signal/termination behavior rather than a harmless
    POSIX-style existence probe.  Opening a limited-information process handle
    does not grant mutation rights; access denial means the process exists but
    is not inspectable.
    """

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        process_query_limited_information = 0x1000
        error_access_denied = 5
        still_active = 259
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() == error_access_denied
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return ctypes.get_last_error() == error_access_denied
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return False


def is_pid_alive(pid: int) -> bool:
    """Return whether a process id appears alive without exposing process data."""

    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        return _is_windows_pid_alive(pid)
    return _is_posix_pid_alive(pid)


def connection_record_candidates(
    path: str | os.PathLike[str] | None = None,
) -> tuple[Path, ...]:
    """Return bounded candidate paths without reading or exposing their contents."""

    if path is not None:
        return (Path(path),)
    candidates: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "freecad-fem-mcp" / "bridge-v1.json")
    candidates.append(Path(os.environ.get("TEMP", os.getcwd())) / "freecad-fem-mcp-connection.json")
    return tuple(candidates)


def connection_record_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Choose the record path to watch for one-shot reconnects."""

    candidates = connection_record_candidates(path)
    if path is not None:
        return candidates[0]
    for candidate in candidates:
        try:
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        except OSError:
            continue
    return candidates[0]


def _validate_record_value(value: Any) -> tuple[dict[str, Any] | None, str]:
    """Validate and normalize an already parsed record without leaking values."""

    if not isinstance(value, dict):
        return None, "record is invalid"
    allowed = {"host", "port", "token", "protocol", "pid", "started_at"}
    if set(value) - allowed:
        return None, "record is invalid"
    host = value.get("host", "127.0.0.1")
    port = value.get("port")
    token = value.get("token")
    protocol = value.get("protocol")
    if protocol is not None and protocol not in {"ndjson-v1", "bridge-v1"}:
        return None, "record is invalid"
    if "pid" in value and (
        not isinstance(value["pid"], int) or isinstance(value["pid"], bool) or value["pid"] <= 0
    ):
        return None, "record is invalid"
    if "started_at" in value:
        started_at = value["started_at"]
        try:
            valid_started_at = (
                isinstance(started_at, (int, float))
                and not isinstance(started_at, bool)
                and math.isfinite(float(started_at))
            )
        except (OverflowError, TypeError, ValueError):
            valid_started_at = False
        if not valid_started_at:
            return None, "record is invalid"
    if not isinstance(host, str) or not isinstance(port, int) or isinstance(port, bool):
        return None, "record is invalid"
    if not isinstance(token, str) or not (24 <= len(token.encode("utf-8")) <= MAX_TOKEN_BYTES):
        return None, "record is invalid"
    try:
        BridgeConfig(host=host, port=port)
    except (ValueError, NameError):
        return None, "record is invalid"
    normalized = {"host": host, "port": port, "token": token}
    if "pid" in value:
        normalized["pid"] = value["pid"]
    if "started_at" in value:
        normalized["started_at"] = value["started_at"]
    return normalized, "record is usable"


def _read_connection_candidate(
    candidate: Path,
    *,
    pid_checker: Callable[[int], bool],
) -> tuple[ConnectionRecordStatus, dict[str, Any] | None, str]:
    """Read one candidate and return only a safe status plus normalized data."""

    try:
        info = candidate.lstat()
        attrs = getattr(info, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(info.st_mode)
            or candidate.is_symlink()
            or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            return "invalid", None, "record is invalid"
        raw_bytes = candidate.read_bytes()
        if len(raw_bytes) > MAX_CONFIG_BYTES:
            return "invalid", None, "record is invalid"
        raw = raw_bytes.decode("utf-8", errors="strict")
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except FileNotFoundError:
        return "missing", None, "record was not found"
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return "invalid", None, "record is invalid"
    normalized, reason = _validate_record_value(value)
    if normalized is None:
        return "invalid", None, reason
    pid = normalized.get("pid")
    if pid is not None:
        try:
            alive = bool(pid_checker(pid))
        except Exception:
            # A process lookup failure is deliberately reported as stale.  The
            # caller must not receive exception text that could contain local
            # process or record details.
            alive = False
        if not alive:
            return "stale", None, "record refers to an exited FreeCAD process"
    return "ready", normalized, reason


def inspect_connection_record(
    path: str | os.PathLike[str] | None = None,
    *,
    pid_checker: Callable[[int], bool] = is_pid_alive,
) -> ConnectionRecordDiagnostic:
    """Safely diagnose the first usable local record or its failure state."""

    saw_invalid = False
    saw_stale = False
    for candidate in connection_record_candidates(path):
        status, _, reason = _read_connection_candidate(candidate, pid_checker=pid_checker)
        if status == "ready":
            return ConnectionRecordDiagnostic("ready", "record is usable")
        saw_invalid |= status == "invalid"
        saw_stale |= status == "stale"
    if saw_stale:
        return ConnectionRecordDiagnostic("stale", "record refers to an exited FreeCAD process")
    if saw_invalid:
        return ConnectionRecordDiagnostic("invalid", "record is invalid")
    return ConnectionRecordDiagnostic("missing", "record was not found")


def load_connection_record(
    path: str | os.PathLike[str] | None = None,
    *,
    pid_checker: Callable[[int], bool] = is_pid_alive,
) -> dict[str, Any] | None:
    """Load the Addon's bounded local connection record, if present.

    The default location is ``%LOCALAPPDATA%/freecad-fem-mcp/bridge-v1.json``;
    the temporary path used by older Addon builds is accepted as a compatibility
    fallback.  A missing record is normal while FreeCAD is not running.  No
    warning includes the token or path contents.
    """

    for candidate in connection_record_candidates(path):
        status, value, _ = _read_connection_candidate(candidate, pid_checker=pid_checker)
        if status == "ready" and value is not None:
            return {key: value[key] for key in ("host", "port", "token")}
    return None


class BridgeError(RuntimeError):
    """Base class for bridge failures safe to expose to the caller."""


class BridgeTransportError(BridgeError):
    """A local transport failure that is eligible for one record refresh."""


class BridgeAuthError(BridgeError):
    """Authentication was not configured or the Addon rejected a request."""


class BridgeProtocolError(BridgeError):
    """The transport returned malformed or unexpected NDJSON."""


class BridgeRemoteError(BridgeError):
    """The Addon returned a JSON-RPC-style error."""


@runtime_checkable
class BridgeTransport(Protocol):
    """Minimal generic bridge method boundary.

    Implementations may expose ``request(line)`` or ``send_line(line)`` and may
    return ``str``/``bytes`` or an awaitable of either.  No transport receives the
    unredacted token except the serialized request line itself.
    """

    def request(self, line: str) -> str | bytes:  # pragma: no cover - protocol declaration
        ...


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    connect_timeout: float = 2.0
    read_timeout: float = 10.0
    max_frame_bytes: int = MAX_FRAME_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host or len(self.host) > 255:
            raise ValueError("invalid bridge host")
        host = self.host.strip().lower().rstrip(".")
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise ValueError("bridge host must be loopback")
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("invalid bridge port")
        if (
            not isinstance(self.connect_timeout, (int, float))
            or isinstance(self.connect_timeout, bool)
            or self.connect_timeout <= 0
            or self.connect_timeout > 60
        ):
            raise ValueError("invalid bridge connect timeout")
        if (
            not isinstance(self.read_timeout, (int, float))
            or isinstance(self.read_timeout, bool)
            or self.read_timeout <= 0
            or self.read_timeout > 120
        ):
            raise ValueError("invalid bridge read timeout")
        if (
            not isinstance(self.max_frame_bytes, int)
            or isinstance(self.max_frame_bytes, bool)
            or not 1024 <= self.max_frame_bytes <= MAX_FRAME_BYTES
        ):
            raise ValueError("invalid bridge frame bound")


class LocalNdjsonTransport:
    """Connect to the local Addon bridge over a bounded TCP NDJSON exchange.

    The Addon is expected to bind only on loopback (or another explicitly chosen
    local host).  A fresh connection per request keeps framing simple and avoids a
    background reader thread in the MCP stdio process.
    """

    def __init__(self, config: BridgeConfig | None = None) -> None:
        self.config = config or BridgeConfig()

    def request(self, line: str) -> str:
        encoded = line.encode("utf-8") + b"\n"
        if len(encoded) > self.config.max_frame_bytes:
            raise BridgeProtocolError("bridge request exceeds frame limit")
        try:
            with socket.create_connection(
                (self.config.host, self.config.port), timeout=self.config.connect_timeout
            ) as connection:
                connection.settimeout(self.config.read_timeout)
                connection.sendall(encoded)
                chunks: list[bytes] = []
                size = 0
                while True:
                    chunk = connection.recv(min(65536, self.config.max_frame_bytes + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > self.config.max_frame_bytes or b"\n" in chunk:
                        break
        except (OSError, TimeoutError) as exc:
            # Do not include host/port details in the message when they could be
            # considered deployment secrets.  Keep the type useful for retries.
            raise BridgeTransportError("unable to reach local FreeCAD bridge") from exc
        response = b"".join(chunks)
        if len(response) > self.config.max_frame_bytes:
            raise BridgeProtocolError("bridge response exceeds frame limit")
        return response.decode("utf-8", errors="strict")


class BridgeClient:
    """Authenticated client for the fixed Addon method surface."""

    def __init__(
        self,
        transport: BridgeTransport | Any,
        token: str | None = None,
        *,
        auth_token: str | None = None,
        secret: str | None = None,
        max_frame_bytes: int = MAX_FRAME_BYTES,
        record_path: str | os.PathLike[str] | None = None,
        connection_record_path: str | os.PathLike[str] | None = None,
        pid_checker: Callable[[int], bool] = is_pid_alive,
        transport_factory: Callable[[BridgeConfig], Any] | None = None,
    ) -> None:
        if record_path is not None and connection_record_path is not None:
            if Path(record_path) != Path(connection_record_path):
                raise ValueError("record_path and connection_record_path disagree")
        if record_path is None:
            record_path = connection_record_path
        supplied = [item for item in (token, auth_token, secret) if item is not None]
        if supplied and any(item != supplied[0] for item in supplied[1:]):
            raise ValueError("bridge authentication values disagree")
        configured = supplied[0] if supplied else None
        if configured is None:
            configured = os.environ.get("FREECAD_FEM_BRIDGE_TOKEN")
        if configured is not None:
            if (
                not isinstance(configured, str)
                or not configured
                or len(configured.encode("utf-8")) > MAX_TOKEN_BYTES
            ):
                raise ValueError("bridge token must be a bounded non-empty string")
        if (
            not isinstance(max_frame_bytes, int)
            or isinstance(max_frame_bytes, bool)
            or not 1024 <= max_frame_bytes <= MAX_FRAME_BYTES
        ):
            raise ValueError("invalid bridge frame bound")
        if transport is None:
            raise ValueError("bridge transport is required")
        self._transport = transport
        self._token = configured
        self._max_frame_bytes = max_frame_bytes
        self._record_path = Path(record_path) if record_path is not None else None
        self._pid_checker = pid_checker
        self._transport_factory = transport_factory
        self._transport_lock = threading.RLock()
        self._counter = itertools.count(1)
        self._counter_lock = threading.Lock()

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    def __repr__(self) -> str:
        return f"BridgeClient(authenticated={self.authenticated!r}, transport={type(self._transport).__name__!r})"

    @staticmethod
    def _check_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
        if params is None:
            return {}
        if not isinstance(params, Mapping):
            raise TypeError("bridge params must be an object")
        # Copy only JSON-compatible data.  json.dumps with allow_nan=False below
        # catches non-finite numbers and unserializable values without logging them.
        return dict(params)

    def _next_id(self) -> int:
        with self._counter_lock:
            return next(self._counter)

    def connection_diagnostic(self) -> ConnectionRecordDiagnostic:
        """Return a safe current record status for diagnostics/health checks."""

        return inspect_connection_record(self._record_path, pid_checker=self._pid_checker)

    def _refresh_from_record(self) -> bool:
        """Refresh credentials/endpoint once from a ready connection record."""

        if self._record_path is None:
            return False
        diagnostic = inspect_connection_record(self._record_path, pid_checker=self._pid_checker)
        if not diagnostic.usable:
            return False
        record = load_connection_record(self._record_path, pid_checker=self._pid_checker)
        if record is None:
            return False
        try:
            config = BridgeConfig(
                host=record["host"],
                port=record["port"],
                connect_timeout=(
                    self._transport.config.connect_timeout
                    if isinstance(self._transport, LocalNdjsonTransport)
                    else 2.0
                ),
                read_timeout=(
                    self._transport.config.read_timeout
                    if isinstance(self._transport, LocalNdjsonTransport)
                    else 10.0
                ),
                max_frame_bytes=self._max_frame_bytes,
            )
        except (KeyError, TypeError, ValueError):
            return False
        replacement = None
        if self._transport_factory is not None:
            try:
                replacement = self._transport_factory(config)
            except Exception:
                return False
        elif isinstance(self._transport, LocalNdjsonTransport):
            replacement = LocalNdjsonTransport(config)
        with self._transport_lock:
            self._token = record["token"]
            if replacement is not None:
                self._transport = replacement
        return True

    def _retry_after_transport_failure(self) -> bool:
        """Allow exactly one bounded record refresh for the current call."""

        try:
            return self._refresh_from_record()
        except Exception:
            # A diagnostic/reload failure is intentionally indistinguishable from
            # an unavailable bridge to avoid leaking local record details.
            return False

    def _encode(self, request_id: int, method: str, params: Mapping[str, Any] | None) -> str:
        if method not in BRIDGE_METHODS:
            raise BridgeProtocolError("bridge method is not allow-listed")
        if len(method.encode("utf-8")) > MAX_METHOD_BYTES:
            raise BridgeProtocolError("bridge method is too long")
        if self._token is None:
            # A long-lived client may have been created while the Addon was
            # restarting, leaving only a stale/missing record at startup.  Do
            # one bounded record refresh before reporting an auth failure so a
            # newly written ready record can bootstrap the first request.
            if self._record_path is not None:
                self._retry_after_transport_failure()
        if self._token is None:
            raise BridgeAuthError("bridge authentication is not configured")
        frame = {
            "id": request_id,
            "method": method,
            "params": self._check_params(params),
            "auth": {"token": self._token},
        }
        try:
            line = json.dumps(frame, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise BridgeProtocolError("bridge request is not valid JSON") from exc
        if len(line.encode("utf-8")) + 1 > self._max_frame_bytes:
            raise BridgeProtocolError("bridge request exceeds frame limit")
        return line

    def _transport_call(self, line: str) -> Any:
        with self._transport_lock:
            transport = self._transport
        method = getattr(transport, "request", None)
        if method is None:
            method = getattr(transport, "send_line", None)
        if method is None:
            method = getattr(transport, "send", None)
        if method is None:
            method = getattr(transport, "exchange", None)
        if method is None and callable(transport):
            method = transport
        if method is None:
            raise TypeError(
                "bridge transport must provide request, send_line, send, exchange, or __call__"
            )
        return method(line)

    async def _transport_call_async(self, line: str) -> Any:
        result = self._transport_call(line)
        if inspect.isawaitable(result):
            return await result
        return result

    def _decode(self, raw: Any, request_id: int) -> Any:
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise BridgeProtocolError("bridge response is not UTF-8") from exc
        if not isinstance(raw, str):
            raise BridgeProtocolError("bridge transport returned a non-text response")
        if len(raw.encode("utf-8")) > self._max_frame_bytes:
            raise BridgeProtocolError("bridge response exceeds frame limit")
        lines = [line for line in raw.splitlines() if line.strip()]
        if len(lines) != 1:
            raise BridgeProtocolError("bridge response must contain exactly one JSON line")
        try:
            response = json.loads(
                lines[0], object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise BridgeProtocolError("bridge response is not valid JSON") from exc
        if not isinstance(response, dict):
            raise BridgeProtocolError("bridge response must be an object")
        unknown = set(response) - {"id", "result", "error"}
        if unknown:
            raise BridgeProtocolError("bridge response has unknown fields")
        if response.get("id") != request_id:
            raise BridgeProtocolError("bridge response id does not match request")
        if "error" in response and "result" in response:
            raise BridgeProtocolError("bridge response cannot contain result and error")
        if "error" in response and response["error"] is not None:
            error = response["error"]
            if isinstance(error, dict):
                message = error.get("message", "remote bridge error")
            else:
                message = "remote bridge error"
            if not isinstance(message, str):
                message = "remote bridge error"
            # Never echo the token even if a misbehaving Addon includes it.
            if self._token:
                message = message.replace(self._token, "[redacted]")
            raise BridgeRemoteError(message[:MAX_ERROR_BYTES])
        if "result" not in response:
            raise BridgeProtocolError("bridge response has no result")
        return response["result"]

    def call(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Synchronously invoke one allow-listed bridge method."""

        request_id = self._next_id()
        line = self._encode(request_id, method, params)
        try:
            result = self._transport_call(line)
            if inspect.isawaitable(result):
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    result = asyncio.run(result)
                else:
                    raise BridgeError("cannot synchronously call an async bridge in a running loop")
        except (BridgeTransportError, OSError, TimeoutError):
            if not self._retry_after_transport_failure():
                raise
            line = self._encode(request_id, method, params)
            result = self._transport_call(line)
            if inspect.isawaitable(result):
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    result = asyncio.run(result)
                else:
                    raise BridgeError("cannot synchronously call an async bridge in a running loop")
        return self._decode(result, request_id)

    async def call_async(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Asynchronously invoke one allow-listed bridge method."""

        request_id = self._next_id()
        line = self._encode(request_id, method, params)
        try:
            result = await self._transport_call_async(line)
        except (BridgeTransportError, OSError, TimeoutError):
            if not self._retry_after_transport_failure():
                raise
            line = self._encode(request_id, method, params)
            result = await self._transport_call_async(line)
        return self._decode(result, request_id)

    # ``request`` is a convenient generic-boundary alias used by tests and by
    # small integrations, while still enforcing the allow-list above.
    request = call
    invoke = call
    call_method = call
    send = call
    request_async = call_async
    send_async = call_async


__all__ = [
    "BRIDGE_METHODS",
    "ALLOWED_METHODS",
    "BridgeAuthError",
    "BridgeClient",
    "BridgeConfig",
    "BridgeError",
    "BridgeTransportError",
    "BridgeProtocolError",
    "BridgeRemoteError",
    "BridgeTransport",
    "LocalNdjsonTransport",
    "ConnectionRecordDiagnostic",
    "connection_record_candidates",
    "connection_record_path",
    "inspect_connection_record",
    "is_pid_alive",
    "load_connection_record",
    "MAX_FRAME_BYTES",
]
