"""Loopback bridge credentials and connection-record handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


class SecurityError(RuntimeError):
    """Raised when credentials or the connection record is invalid."""


@dataclass(frozen=True)
class StartupCredentials:
    token: str
    host: str
    port: int
    pid: int
    started_at: float
    record_path: str

    def record(self) -> Mapping[str, Any]:
        return {
            "host": self.host, "port": self.port, "pid": self.pid,
            "started_at": self.started_at, "token": self.token,
            "protocol": "ndjson-v1",
        }


def _safe_record_path(path: Optional[os.PathLike[str] | str]) -> Path:
    if path is not None:
        candidate = Path(path)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidate = Path(local_app_data) / "freecad-fem-mcp" / "bridge-v1.json"
        else:
            candidate = Path(tempfile.gettempdir()) / "freecad-fem-mcp-connection.json"
    if candidate.name in {"", ".", ".."}:
        raise SecurityError("connection record must be a file path")
    return candidate


class TokenAuthenticator:
    """Create and verify a random per-start token in constant time."""

    def __init__(self, token: Optional[str] = None):
        self._token = token or secrets.token_urlsafe(32)
        if not isinstance(self._token, str) or not (24 <= len(self._token) <= 256):
            raise SecurityError("token has an invalid length")
        self._digest = hashlib.sha256(self._token.encode("utf-8")).digest()

    @property
    def token(self) -> str:
        return self._token

    def authenticate(self, supplied: Any) -> bool:
        if not isinstance(supplied, str):
            return False
        try:
            candidate = hashlib.sha256(supplied.encode("utf-8")).digest()
        except UnicodeError:
            return False
        return hmac.compare_digest(candidate, self._digest)

    def make_credentials(self, host: str, port: int, record_path: Optional[os.PathLike[str] | str] = None) -> StartupCredentials:
        if host != "127.0.0.1":
            raise SecurityError("bridge host must be 127.0.0.1")
        if not isinstance(port, int) or not 0 < port <= 65535:
            raise SecurityError("invalid bridge port")
        return StartupCredentials(self._token, host, port, os.getpid(), time.time(), str(_safe_record_path(record_path)))

    @staticmethod
    def write_record(credentials: StartupCredentials) -> str:
        path = _safe_record_path(credentials.record_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(credentials.record(), separators=(",", ":"), ensure_ascii=True)
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            try:
                os.fchmod(fd, 0o600)
            except (AttributeError, OSError):
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            os.replace(temporary, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return str(path)
