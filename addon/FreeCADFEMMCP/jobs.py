"""Bounded asynchronous Gmsh/CalculiX process jobs.

FreeCAD's FEM tools expose QProcess-backed runners.  The registry accepts only
trusted executable paths configured by the addon and never invokes a shell.
"""

from __future__ import annotations

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

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "state": self.state,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "exit_code": self.exit_code, "output": self.output[-32768:],
            "error": self.error, "artifacts": dict(self.artifacts),
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
                reader = getattr(process, "readAllStandardOutput", None)
                if callable(reader):
                    data = reader()
                    if isinstance(data, bytes):
                        text = data.decode("utf-8", "replace")
                    else:
                        text = str(data)
                    job.output = (job.output + text)[-self.max_output:]

            ready = getattr(process, "readyReadStandardOutput", None)
            if ready is not None and hasattr(ready, "connect"):
                ready.connect(output)

            def finalize() -> None:
                output()
                code = getattr(process, "exitCode", lambda: 0)()
                job.exit_code = int(code)
                job.state = "completed" if code == 0 else "failed"
                job.finished_at = time.time()
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
            job.state, job.error, job.finished_at = "failed", str(exc), time.time()
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

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [job.summary() for job in list(self._jobs.values())[-self.max_jobs:]]

    def cancel(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError("job not found")
            if job.state in {"queued", "running"} and job.process is not None:
                killer = getattr(job.process, "kill", None)
                if callable(killer):
                    killer()
                else:
                    terminator = getattr(job.process, "terminate", None)
                    if callable(terminator):
                        terminator()
                job.state = "cancelled"
                job.finished_at = time.time()
            return job.summary()


# Short compatibility spelling for callers that do not need to mention the Qt
# implementation detail in their type annotations.
JobRegistry = QProcessJobRegistry
