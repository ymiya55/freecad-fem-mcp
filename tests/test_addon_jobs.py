"""Dependency-free fake-QProcess coverage for the Addon job registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "addon"))

from FreeCADFEMMCP.jobs import JobError, QProcessJobRegistry  # noqa: E402


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class _FakeProcess:
    def __init__(self, *, finish_on_run=False, running_after_terminate=False):
        self.readyReadStandardOutput = _Signal()
        self.readyReadStandardError = _Signal()
        self.finished = _Signal()
        self.stdout = b""
        self.stderr = b""
        self.finish_on_run = finish_on_run
        self.running_after_terminate = running_after_terminate
        self.terminated = False
        self.killed = False
        self.waits = []
        self._exit_code = 0

    def readAllStandardOutput(self):
        value, self.stdout = self.stdout, b""
        return value

    def readAllStandardError(self):
        value, self.stderr = self.stderr, b""
        return value

    def exitCode(self):
        return self._exit_code

    def terminate(self):
        self.terminated = True
        if not self.running_after_terminate:
            self._exit_code = -15

    def kill(self):
        self.killed = True
        self._exit_code = -9

    def waitForFinished(self, timeout):
        self.waits.append(timeout)

    def state(self):
        return self.running_after_terminate and not self.killed


class _FakeTool:
    def __init__(self, process, finish_on_run=False):
        self.process = process
        self.finish_on_run = finish_on_run

    def run(self, blocking):
        assert blocking is False
        self.process.stdout = b"\xffstdout-value"
        self.process.stderr = b"stderr-value"
        self.process.readyReadStandardOutput.emit()
        self.process.readyReadStandardError.emit()
        if self.finish_on_run:
            self.process.finished.emit(0, 0)


def test_output_is_utf8_decoded_and_bounded_without_bytes_repr():
    process = _FakeProcess(finish_on_run=True)
    registry = QProcessJobRegistry(gmsh_factory=lambda _obj: _FakeTool(process, True), max_output=1024)
    summary = registry.start_gmsh(object())
    assert summary["state"] == "completed"
    assert "stdout-value" in summary["output"]
    assert "stderr-value" in summary["output"]
    assert "b'" not in summary["output"]
    assert "�" in summary["output"]
    assert len(summary["output"].encode("utf-8")) <= 1024


def test_cancel_queued_running_completed_and_unknown_states():
    registry = QProcessJobRegistry(gmsh_factory=lambda _obj: _FakeTool(_FakeProcess()))
    queued = registry._new("gmsh")
    assert registry.cancel(queued.id)["state"] == "cancelled"

    running_process = _FakeProcess(running_after_terminate=False)
    running_registry = QProcessJobRegistry(gmsh_factory=lambda _obj: _FakeTool(running_process))
    running = running_registry.start_gmsh(object())
    cancelled = running_registry.cancel(running["id"])
    assert cancelled["state"] == "cancelled"
    assert running_process.terminated is True
    assert running_process.killed is False

    completed_process = _FakeProcess(finish_on_run=True)
    completed_registry = QProcessJobRegistry(gmsh_factory=lambda _obj: _FakeTool(completed_process, True))
    completed = completed_registry.start_gmsh(object())
    assert completed_registry.cancel(completed["id"])["state"] == "completed"
    with pytest.raises(JobError):
        registry.cancel("unknown-job")


def test_cancel_escalates_to_kill_when_terminate_does_not_stop_process():
    process = _FakeProcess(running_after_terminate=True)
    registry = QProcessJobRegistry(gmsh_factory=lambda _obj: _FakeTool(process))
    running = registry.start_gmsh(object())
    assert registry.cancel(running["id"])["state"] == "cancelled"
    assert process.terminated is True
    assert process.killed is True
    assert process.waits == [100]


def test_failure_diagnostic_is_bounded_and_redacts_secrets():
    def broken(_obj):
        raise RuntimeError("token=super-secret password=hidden " + "x" * 5000)

    registry = QProcessJobRegistry(gmsh_factory=broken)
    summary = registry.start_gmsh(object())
    assert summary["state"] == "failed"
    assert "super-secret" not in summary["error"]
    assert "hidden" not in summary["error"]
    assert len(summary["error"].encode("utf-8")) <= 2048
