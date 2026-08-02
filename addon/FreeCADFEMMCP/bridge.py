"""Authenticated, loopback-only background NDJSON bridge."""

from __future__ import annotations

import logging
import socket
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .dispatcher import DispatchFull, MainThreadDispatcher
from .protocol import (
    MAX_FRAME_BYTES, BridgeError, ProtocolError, Request, Response,
    error_response, parse_request_line, serialize_response,
)
from .security import StartupCredentials, TokenAuthenticator

LOG = logging.getLogger(__name__)
MAX_CONNECTIONS = 16
MAX_LOG_ENTRIES = 512


@dataclass(frozen=True)
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 0
    max_frame_bytes: int = MAX_FRAME_BYTES
    max_queue: int = 64
    request_timeout: float = 30.0
    backlog: int = 8
    connection_record: Optional[str] = None
    allowed_roots: tuple[str, ...] = ()


class LocalhostBridge:
    """Small TCP listener with one request per NDJSON line.

    The listener thread performs only framing/authentication and hands native
    FreeCAD work to ``MainThreadDispatcher``.  Input is never interpreted as
    Python, a shell command, or a module name.
    """

    def __init__(self, handler: Callable[[Request], Any], config: BridgeConfig = BridgeConfig(), dispatcher: Optional[MainThreadDispatcher] = None):
        if config.host != "127.0.0.1":
            raise BridgeError("bridge may bind only to 127.0.0.1")
        if not 0 <= config.port <= 65535:
            raise BridgeError("invalid bridge port")
        if not 1024 <= config.max_frame_bytes <= 4 * 1024 * 1024:
            raise BridgeError("invalid frame limit")
        if not 1 <= config.max_queue <= 4096:
            raise BridgeError("invalid queue limit")
        self.config = config
        self._handler = handler
        self._dispatcher = dispatcher or MainThreadDispatcher(config.max_queue)
        self._auth = TokenAuthenticator()
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._credentials: Optional[StartupCredentials] = None
        self._log: list[str] = []
        self._log_lock = threading.Lock()
        self._connections = threading.BoundedSemaphore(MAX_CONNECTIONS)

    @property
    def token(self) -> str:
        """Bootstrap-only accessor; never included in protocol responses."""
        return self._auth.token

    @property
    def credentials(self) -> Optional[StartupCredentials]:
        return self._credentials

    @property
    def address(self) -> Optional[tuple[str, int]]:
        if self._sock is None:
            return None
        return self._sock.getsockname()

    def _record(self, message: str) -> None:
        # Keep logs bounded and avoid accidental credential leakage.
        lowered = message.lower()
        if "token" in lowered or "secret" in lowered or "password" in lowered:
            message = "[redacted]"
        with self._log_lock:
            self._log.append(message[:512])
            del self._log[:-MAX_LOG_ENTRIES]

    def logs(self) -> list[str]:
        with self._log_lock:
            return list(self._log)

    def start(self) -> StartupCredentials:
        if self._sock is not None:
            if self._credentials is None:
                raise BridgeError("bridge has no credentials")
            return self._credentials
        if self._stop.is_set():
            self._dispatcher = MainThreadDispatcher(self.config.max_queue)
            self._auth = TokenAuthenticator()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            sock.bind(("127.0.0.1", self.config.port))
            sock.listen(self.config.backlog)
            sock.settimeout(0.5)
        except Exception:
            sock.close()
            raise
        self._sock = sock
        host, port = sock.getsockname()
        self._credentials = self._auth.make_credentials(host, port, self.config.connection_record)
        TokenAuthenticator.write_record(self._credentials)
        self._stop.clear()
        self._thread = threading.Thread(target=self._accept_loop, name="FreeCADFEMMCP-bridge", daemon=True)
        self._thread.start()
        self._record("bridge started on 127.0.0.1:{}".format(port))
        return self._credentials

    def stop(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._dispatcher.close()

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                connection, address = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if address[0] != "127.0.0.1":
                connection.close()
                continue
            if not self._connections.acquire(blocking=False):
                connection.close()
                continue
            worker = threading.Thread(target=self._client_loop, args=(connection,), daemon=True)
            worker.start()

    def _client_loop(self, connection: socket.socket) -> None:
        try:
            connection.settimeout(self.config.request_timeout)
            buffer = b""
            while not self._stop.is_set():
                chunk = connection.recv(8192)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > self.config.max_frame_bytes and b"\n" not in buffer:
                    connection.sendall(error_response(None, "too_large", "request exceeds frame limit"))
                    break
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if len(line) > self.config.max_frame_bytes:
                        connection.sendall(error_response(None, "too_large", "request exceeds frame limit"))
                        return
                    try:
                        request = parse_request_line(line, self.config.max_frame_bytes)
                        if not self._auth.authenticate(request.token):
                            response = error_response(request.request_id, "unauthorized", "authentication failed")
                        else:
                            try:
                                result = self._dispatcher.submit(lambda request=request: self._handler(request), timeout=self.config.request_timeout)
                                response = serialize_response(Response(request.request_id, result=result), self.config.max_frame_bytes)
                            except DispatchFull:
                                response = error_response(request.request_id, "busy", "request queue is full")
                            except TimeoutError:
                                response = error_response(request.request_id, "timeout", "request timed out")
                            except Exception:
                                LOG.exception("bridge request failed")
                                response = error_response(request.request_id, "internal_error", "operation failed")
                    except ProtocolError as exc:
                        response = error_response(exc.request_id, exc.code, str(exc))
                    connection.sendall(response)
                if len(buffer) > self.config.max_frame_bytes:
                    connection.sendall(error_response(None, "too_large", "request exceeds frame limit"))
                    return
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                connection.close()
            except OSError:
                pass
            self._connections.release()
