"""Main-thread dispatch for FreeCAD/Qt and a deterministic test fallback."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:  # FreeCAD 1.1.3 ships PySide6; older installations may expose PySide2.
    from PySide import QtCore  # type: ignore
except ImportError:  # pragma: no cover - exercised only in a host with PySide2
    try:
        from PySide2 import QtCore  # type: ignore
    except ImportError:  # protocol/security tests run in a plain Python process
        QtCore = None  # type: ignore


class DispatchFull(RuntimeError):
    pass


@dataclass
class _Ticket:
    event: threading.Event
    result: Any = None
    error: Optional[BaseException] = None


if QtCore is not None:  # pragma: no cover - Qt is unavailable in CI
    class _SignalProxy(QtCore.QObject):
        ready = QtCore.Signal()


class MainThreadDispatcher:
    """Bounded callable queue whose Qt signal is delivered on the GUI thread."""

    def __init__(self, max_queue: int = 64):
        if not isinstance(max_queue, int) or not 1 <= max_queue <= 4096:
            raise ValueError("max_queue must be between 1 and 4096")
        self._queue: queue.Queue[tuple[Callable[[], Any], _Ticket]] = queue.Queue(maxsize=max_queue)
        self._max_queue = max_queue
        self._owner_thread = threading.get_ident()
        self._closed = False
        self._proxy = None
        if QtCore is not None:
            self._proxy = _SignalProxy()
            self._proxy.ready.connect(self._drain)  # type: ignore[union-attr]

    @property
    def is_qt(self) -> bool:
        return self._proxy is not None

    @property
    def owner_thread(self) -> int:
        return self._owner_thread

    def submit(self, callback: Callable[[], Any], wait: bool = True, timeout: float = 30.0) -> Any:
        if self._closed:
            raise RuntimeError("dispatcher is closed")
        if not callable(callback):
            raise TypeError("callback must be callable")
        # In a plain Python process there is no GUI event loop.  Running the
        # bounded operation synchronously keeps security/protocol tests useful
        # while FreeCAD always uses the Qt signal path.
        if self._proxy is None:
            return callback()
        ticket = _Ticket(threading.Event())
        try:
            self._queue.put_nowait((callback, ticket))
        except queue.Full as exc:
            raise DispatchFull("main-thread queue is full") from exc
        self._proxy.ready.emit()
        if not wait:
            return None
        if not ticket.event.wait(timeout):
            raise TimeoutError("main-thread operation timed out")
        if ticket.error is not None:
            raise ticket.error
        return ticket.result

    @QtCore.Slot() if QtCore is not None else (lambda function: function)
    def _drain(self) -> None:
        # Qt invokes this slot on the thread owning ``_proxy`` (the GUI/main
        # thread).  A bounded loop prevents a flood from starving the UI.
        while True:
            try:
                callback, ticket = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                ticket.result = callback()
            except BaseException as exc:  # propagate to waiting socket thread
                ticket.error = exc
            finally:
                ticket.event.set()
                self._queue.task_done()

    def run_pending(self, limit: int = 64) -> int:
        """Drain queued work explicitly (useful for headless host tests)."""
        if self._proxy is not None and threading.get_ident() != self._owner_thread:
            raise RuntimeError("run_pending must be called on the owner thread")
        count = 0
        while count < limit:
            try:
                callback, ticket = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                ticket.result = callback()
            except BaseException as exc:
                ticket.error = exc
            finally:
                ticket.event.set()
                self._queue.task_done()
            count += 1
        return count

    def close(self) -> None:
        self._closed = True
        while True:
            try:
                _, ticket = self._queue.get_nowait()
            except queue.Empty:
                break
            ticket.error = RuntimeError("dispatcher is closed")
            ticket.event.set()
            self._queue.task_done()
