"""Bounded asynchronous Gmsh/CalculiX process jobs.

FreeCAD's FEM tools expose QProcess-backed runners.  The registry accepts only
trusted executable paths configured by the addon and never invokes a shell.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    from PySide import QtCore  # type: ignore
except ImportError:  # pragma: no cover
    try:
        from PySide2 import QtCore  # type: ignore
    except ImportError:
        QtCore = None  # type: ignore
try:
    from femmesh import gmshtools as _gmshtools  # type: ignore
    _GmshTools = _gmshtools.GmshTools
except ImportError:
    try:
        from femmesh.gmshtools import GmshTools as _GmshTools  # type: ignore
    except ImportError:
        _GmshTools = None
try:
    from femsolver.calculix.calculixtools import CalculiXTools as _CalculiXTools  # type: ignore
except ImportError:
    _CalculiXTools = None


class JobError(RuntimeError):
    pass


_MAX_DIAGNOSTIC_BYTES = 2048
_SECRET_DIAGNOSTIC = re.compile(r"(?i)(token|secret|password|credential)\s*([:=])\s*[^\s,;]+")
_CONVERGED_RE = re.compile(
    r"(?i)\b(?:nonlinear\s+)?(?:analysis|solution)\s+(converged|not\s+converged|failed)\b"
)
_INCREMENT_RE = re.compile(
    r"(?i)\b(?:final\s+)?(?:increment|iteration|step)\s*[:=#]?\s*(\d{1,7})\s*(?:\b|$)"
)


def _clip_utf8(value: str, maximum: int) -> str:
    raw = value.encode("utf-8", "replace")
    if len(raw) <= maximum:
        return value
    return raw[-maximum:].decode("utf-8", "ignore")


def _safe_diagnostic(value: Any) -> str:
    text = str(value).replace("\x00", "�")
    text = "".join(character if character in "\r\n\t" or ord(character) >= 0x20 else "�" for character in text)
    text = _SECRET_DIAGNOSTIC.sub(lambda match: "{}{}[redacted]".format(match.group(1), match.group(2)), text)
    return _clip_utf8(text, _MAX_DIAGNOSTIC_BYTES)


def _decode_process_bytes(value: Any) -> str:
    """Decode QByteArray/bytes output without Python ``b'...'`` repr leakage."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
    else:
        try:
            raw = bytes(value)
        except (TypeError, ValueError):
            raw = str(value).encode("utf-8", "replace")
    return _safe_diagnostic(raw.decode("utf-8", "replace"))


def _convergence_summary(output: str, state: str) -> Optional[Dict[str, Any]]:
    """Extract only explicit, bounded convergence markers from native output.

    CalculiX output wording varies across builds.  We intentionally avoid
    guessing from an exit code or arbitrary numeric lines: a summary is emitted
    only when a stable known phrase is present, and increments are capped.
    """

    if not output:
        return None
    match = _CONVERGED_RE.search(output)
    if match is None:
        return None
    convergence_word = match.group(1).lower().replace(" ", "_")
    status = "converged" if convergence_word == "converged" else "not_converged"
    increment = None
    increment_match = None
    for candidate in _INCREMENT_RE.finditer(output):
        increment_match = candidate
    if increment_match is not None:
        try:
            value = int(increment_match.group(1))
            if 0 <= value <= 1_000_000:
                increment = value
        except (TypeError, ValueError, OverflowError):
            pass
    result: Dict[str, Any] = {
        "status": status,
        "source": "native_output",
    }
    if increment is not None:
        result["final_increment"] = increment
    # A process marked failed must never be reported as converged, even if a
    # trailing diagnostic contains the word "converged".
    if state != "completed" and status == "converged":
        result["status"] = "not_converged"
    return result


@dataclass
class Job:
    id: str
    kind: str
    state: str = "queued"
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None
    output: str = ""
    error: Optional[str] = None
    process: Any = None
    native_object: Any = None
    artifacts: Dict[str, str] = field(default_factory=dict)
    convergence: Optional[Dict[str, Any]] = None

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "state": self.state,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "exit_code": self.exit_code, "output": self.output[-32768:],
            "error": _safe_diagnostic(self.error) if self.error else None,
            "artifacts": dict(self.artifacts),
            "convergence": dict(self.convergence) if self.convergence is not None else None,
        }


class QProcessJobRegistry:
    """Track native FreeCAD GmshTools/CalculiXTools QProcess jobs.

    The tools own executable discovery, input writing, and result import.  No
    shell or raw executable path is accepted from protocol input.
    """

    def __init__(self, gmsh_factory: Optional[Callable[[Any], Any]] = None, calculix_factory: Optional[Callable[[Any], Any]] = None, max_jobs: int = 16, max_output: int = 32768):
        if not 1 <= max_jobs <= 128 or not 1024 <= max_output <= 1024 * 1024:
            raise ValueError("job bounds are invalid")
        self.gmsh_factory = gmsh_factory or _GmshTools
        self.calculix_factory = calculix_factory or _CalculiXTools
        self.max_jobs, self.max_output = max_jobs, max_output
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.RLock()

    def _new(self, kind: str) -> Job:
        with self._lock:
            active = sum(job.state in {"queued", "running"} for job in self._jobs.values())
            if active >= self.max_jobs:
                raise JobError("job registry is full")
            job = Job(id=secrets.token_hex(12), kind=kind)
            self._jobs[job.id] = job
            return job

    def _start_native(self, kind: str, factory: Optional[Callable[[Any], Any]], native_object: Any) -> Job:
        if factory is None:
            raise JobError("{} native tool is not available".format(kind))
        job = self._new(kind)
        try:
            tool = factory(native_object)
            job.native_object = native_object
            job.tool = tool  # type: ignore[attr-defined]  # retain until result import completes
            process = getattr(tool, "process", None)
            if process is None:
                raise JobError("native tool did not expose QProcess")
            job.process, job.state = process, "running"
            merger = getattr(process, "setProcessChannelMode", None)
            merged = getattr(QtCore, "QProcess", None) if QtCore is not None else None
            if callable(merger) and merged is not None:
                try:
                    merger(merged.MergedChannels)
                except Exception:
                    pass

            def output() -> None:
                chunks = []
                for reader_name in ("readAllStandardOutput", "readAllStandardError"):
                    reader = getattr(process, reader_name, None)
                    if callable(reader):
                        try:
                            chunks.append(_decode_process_bytes(reader()))
                        except (AttributeError, RuntimeError, TypeError, ValueError):
                            continue
                if chunks:
                    job.output = _clip_utf8(job.output + "".join(chunks), self.max_output)

            ready = getattr(process, "readyReadStandardOutput", None)
            if ready is not None and hasattr(ready, "connect"):
                ready.connect(output)
            ready_error = getattr(process, "readyReadStandardError", None)
            if ready_error is not None and hasattr(ready_error, "connect"):
                ready_error.connect(output)

            def finalize() -> None:
                if job.state == "cancelled":
                    return
                output()
                code = getattr(process, "exitCode", lambda: 0)()
                job.exit_code = int(code)
                job.state = "completed" if code == 0 else "failed"
                job.finished_at = time.time()
                job.convergence = _convergence_summary(job.output, job.state)
                # CalculiXTools' internal finished handler imports its native
                # FemPostPipeline before this callback runs.
                if kind == "calculix":
                    results = getattr(native_object, "Results", None)
                    if results is not None:
                        job.artifacts["results_type"] = str(getattr(results, "TypeId", "Fem::FemPostPipeline"))

            def finished(*_args: Any) -> None:
                # ObjectTools connected its result-import slot in the native
                # tool constructor before this registry callback. Qt preserves
                # that connection order, so importing is complete here.  Do
                # not defer through QTimer: FreeCADCmd has no continuously
                # running GUI event loop and the timer would leave jobs stuck.
                finalize()
            signal = getattr(process, "finished", None)
            if signal is not None and hasattr(signal, "connect"):
                signal.connect(finished)
            runner = getattr(tool, "run", None)
            if not callable(runner):
                raise JobError("native tool did not expose run()")
            runner(False)
        except Exception as exc:
            job.state, job.error, job.finished_at = "failed", _safe_diagnostic(exc), time.time()
        return job

    def start_gmsh(self, mesh_object: Any) -> Dict[str, Any]:
        return self._start_native("gmsh", self.gmsh_factory, mesh_object).summary()

    def start_calculix(self, solver_object: Any) -> Dict[str, Any]:
        return self._start_native("calculix", self.calculix_factory, solver_object).summary()

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError("job not found")
            return job.summary()

    def native_object(self, job_id: str) -> Any:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError("job not found")
            return job.native_object

    def find_for_object(self, native_object: Any, kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            for job in reversed(list(self._jobs.values())):
                if job.native_object is native_object and (kind is None or job.kind == kind):
                    return job.summary()
        return None

    def wait(self, job_id: str, timeout_ms: int = 50) -> None:
        """Give a native QProcess a bounded wait turn for headless FreeCADCmd."""
        if not isinstance(timeout_ms, int) or not 1 <= timeout_ms <= 1000:
            raise JobError("wait timeout is invalid")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError("job not found")
            process = job.process
        waiter = getattr(process, "waitForFinished", None) if process is not None else None
        if callable(waiter):
            waiter(timeout_ms)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [job.summary() for job in list(self._jobs.values())[-self.max_jobs:]]

    def cancel(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError("job not found")
            if job.state == "queued":
                job.state = "cancelled"
                job.finished_at = time.time()
            elif job.state == "running":
                # Mark cancelled before signaling QProcess so a synchronous
                # finished callback cannot turn a user cancellation into
                # completed/failed.
                job.state = "cancelled"
                process = job.process
                terminator = getattr(process, "terminate", None) if process is not None else None
                killer = getattr(process, "kill", None) if process is not None else None
                try:
                    if callable(terminator):
                        terminator()
                        waiter = getattr(process, "waitForFinished", None)
                        state_getter = getattr(process, "state", None)
                        still_running = False
                        if callable(waiter):
                            waiter(100)
                        if callable(state_getter):
                            try:
                                still_running = bool(state_getter())
                            except Exception:
                                still_running = False
                        if still_running and callable(killer):
                            killer()
                    elif callable(killer):
                        killer()
                except Exception as exc:
                    job.error = _safe_diagnostic(exc)
                job.finished_at = time.time()
            return job.summary()


# Short compatibility spelling for callers that do not need to mention the Qt
# implementation detail in their type annotations.
JobRegistry = QProcessJobRegistry
