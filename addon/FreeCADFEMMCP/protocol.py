"""Bounded NDJSON protocol primitives used by the local bridge."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

MAX_FRAME_BYTES = 1024 * 1024
MAX_ID_BYTES = 128
MAX_METHOD_BYTES = 64
MAX_PARAMS_BYTES = 192 * 1024

# Public MCP bridge method names are deliberately generic and map one-to-one
# to the core service contract.  Each request carries an ``action`` in params.
ALLOWED_METHODS = frozenset({
    "status", "document", "selection", "view", "capture", "open", "save",
    "analysis", "material", "constraint", "load", "boundary_condition", "remote_load", "mesh",
    "validate", "jobs", "results",
})


class ProtocolError(ValueError):
    def __init__(self, message: str, request_id: Any = None, code: str = "invalid_request"):
        super().__init__(message)
        self.request_id, self.code = request_id, code


class BridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Request:
    request_id: Any
    method: str
    params: Mapping[str, Any]
    token: Optional[str] = None


@dataclass(frozen=True)
class Response:
    request_id: Any
    result: Any = None
    error: Optional[Mapping[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        if self.error is not None:
            return {"id": self.request_id, "error": dict(self.error)}
        return {"id": self.request_id, "result": self.result}


def _check_json_size(value: Any, maximum: int, label: str) -> None:
    try:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProtocolError("{} is not JSON serializable".format(label)) from exc
    if len(encoded) > maximum:
        raise ProtocolError("{} exceeds the size limit".format(label), code="too_large")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ProtocolError("non-standard JSON constant")


def parse_request_line(line: bytes | str, max_frame_bytes: int = MAX_FRAME_BYTES) -> Request:
    if isinstance(line, bytes):
        raw = line
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("request is not UTF-8") from exc
    elif isinstance(line, str):
        text, raw = line, line.encode("utf-8")
    else:
        raise ProtocolError("request must be bytes or text")
    if len(raw) > max_frame_bytes:
        raise ProtocolError("request exceeds frame limit", code="too_large")
    text = text.strip()
    if not text:
        raise ProtocolError("empty request")
    try:
        value = json.loads(text, object_pairs_hook=_pairs_no_duplicates, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise ProtocolError("request is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("request must be a JSON object")
    request_id = value.get("id")
    if request_id is None or isinstance(request_id, (dict, list)) or (isinstance(request_id, float) and not math.isfinite(request_id)):
        raise ProtocolError("request id must be a scalar", request_id=request_id)
    if len(json.dumps(request_id, ensure_ascii=False).encode("utf-8")) > MAX_ID_BYTES:
        raise ProtocolError("request id is too long", request_id=request_id, code="too_large")
    method = value.get("method")
    if not isinstance(method, str) or not method or len(method.encode("utf-8")) > MAX_METHOD_BYTES:
        raise ProtocolError("method must be a short string", request_id=request_id)
    if method not in ALLOWED_METHODS:
        raise ProtocolError("method is not allowed", request_id=request_id, code="method_not_allowed")
    params = value.get("params", {})
    if not isinstance(params, dict):
        raise ProtocolError("params must be an object", request_id=request_id)
    _check_json_size(params, MAX_PARAMS_BYTES, "params")
    unknown = set(value) - {"id", "method", "params", "auth"}
    if unknown:
        raise ProtocolError("unknown request fields", request_id=request_id)
    auth = value.get("auth")
    token = None
    if auth is not None:
        if not isinstance(auth, dict) or set(auth) != {"token"} or not isinstance(auth["token"], str) or len(auth["token"]) > 256:
            raise ProtocolError("invalid authentication field", request_id=request_id)
        token = auth["token"]
    return Request(request_id, method, params, token)


_SENSITIVE_KEYS = {"token", "auth", "secret", "password", "credential"}


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_sensitive(item) for key, item in value.items() if str(key).lower() not in _SENSITIVE_KEYS}
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    return value


def serialize_response(response: Response | Mapping[str, Any], max_frame_bytes: int = MAX_FRAME_BYTES) -> bytes:
    value = response.as_dict() if isinstance(response, Response) else dict(response)
    value = _strip_sensitive(value)
    try:
        encoded = (json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProtocolError("response is not JSON serializable") from exc
    if len(encoded) > max_frame_bytes:
        raise ProtocolError("response exceeds frame limit", code="too_large")
    return encoded


def error_response(request_id: Any, code: str, message: str) -> bytes:
    return serialize_response(Response(request_id, error={"code": code, "message": message}))
