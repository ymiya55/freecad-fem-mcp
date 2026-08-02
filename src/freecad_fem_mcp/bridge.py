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
from typing import Any, Protocol, runtime_checkable

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


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-standard JSON number")


def load_connection_record(path: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    """Load the Addon's bounded local connection record, if present.

    The default location is ``%LOCALAPPDATA%/freecad-fem-mcp/bridge-v1.json``;
    the temporary path used by older Addon builds is accepted as a compatibility
    fallback.  A missing record is normal while FreeCAD is not running.  No
    warning includes the token or path contents.
    """

    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    else:
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            candidates.append(Path(local_appdata) / "freecad-fem-mcp" / "bridge-v1.json")
        candidates.append(
            Path(os.environ.get("TEMP", os.getcwd())) / "freecad-fem-mcp-connection.json"
        )
    for candidate in candidates:
        try:
            # Do not follow symlinks/reparse points for credentials.  On POSIX
            # ``is_symlink`` catches links; Windows ``st_file_attributes`` catches
            # reparse points without requiring pywin32.
            info = candidate.lstat()
            if not stat.S_ISREG(info.st_mode) or candidate.is_symlink():
                continue
            attrs = getattr(info, "st_file_attributes", 0)
            if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                continue
            if len(candidate.read_bytes()) > MAX_CONFIG_BYTES:
                continue
            raw = candidate.read_text(encoding="utf-8")
            value = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        allowed = {"host", "port", "token", "protocol", "pid", "started_at"}
        if set(value) - allowed:
            continue
        host = value.get("host", "127.0.0.1")
        port = value.get("port")
        token = value.get("token")
        protocol = value.get("protocol")
        if protocol is not None and protocol not in {"ndjson-v1", "bridge-v1"}:
            continue
        if "pid" in value and (
            not isinstance(value["pid"], int) or isinstance(value["pid"], bool) or value["pid"] <= 0
        ):
            continue
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
                continue
        if not isinstance(host, str) or not isinstance(port, int) or isinstance(port, bool):
            continue
        if not isinstance(token, str) or not (24 <= len(token.encode("utf-8")) <= MAX_TOKEN_BYTES):
            continue
        try:
            BridgeConfig(host=host, port=port)
        except (ValueError, NameError):
            # BridgeConfig is defined below; this branch only matters if this
            # helper is invoked during module initialisation.
            continue
        return {"host": host, "port": port, "token": token}
    return None


class BridgeError(RuntimeError):
    """Base class for bridge failures safe to expose to the caller."""


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
            raise BridgeError("unable to reach local FreeCAD bridge") from exc
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
    ) -> None:
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

    def _encode(self, request_id: int, method: str, params: Mapping[str, Any] | None) -> str:
        if method not in BRIDGE_METHODS:
            raise BridgeProtocolError("bridge method is not allow-listed")
        if len(method.encode("utf-8")) > MAX_METHOD_BYTES:
            raise BridgeProtocolError("bridge method is too long")
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
    "BridgeProtocolError",
    "BridgeRemoteError",
    "BridgeTransport",
    "LocalNdjsonTransport",
    "load_connection_record",
    "MAX_FRAME_BYTES",
]
