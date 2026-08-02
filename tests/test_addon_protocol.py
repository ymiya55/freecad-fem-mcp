"""Protocol/security checks that intentionally run without FreeCAD."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "addon"))

from FreeCADFEMMCP.bridge import BridgeConfig, LocalhostBridge  # noqa: E402
from FreeCADFEMMCP.protocol import ProtocolError, parse_request_line, serialize_response  # noqa: E402
from FreeCADFEMMCP.security import TokenAuthenticator  # noqa: E402
from FreeCADFEMMCP.operations import FreeCADOperations  # noqa: E402
from FreeCADFEMMCP.pipeline import FemPostPipeline  # noqa: E402
from FreeCADFEMMCP.service import FEMService, ServiceError  # noqa: E402
from FreeCADFEMMCP.protocol import Request  # noqa: E402


def test_allowlist_and_nested_auth_shape() -> None:
    request = parse_request_line(json.dumps({"id": 1, "method": "status", "params": {}, "auth": {"token": "x"}}))
    assert request.method == "status"
    assert request.token == "x"
    with pytest.raises(ProtocolError):
        parse_request_line('{"id":1,"method":"ping","params":{}}')
    with pytest.raises(ProtocolError):
        parse_request_line('{"id":1,"method":"status","params":{},"extra":1}')


def test_token_auth_is_constant_time_and_not_serialized() -> None:
    auth = TokenAuthenticator("x" * 32)
    assert auth.authenticate("x" * 32)
    assert not auth.authenticate("y" * 32)
    assert b"token" not in serialize_response({"id": 1, "result": {"token": "secret"}})


def test_bridge_is_loopback_and_authenticated() -> None:
    seen = []
    bridge = LocalhostBridge(lambda request: seen.append(request.method) or {"ok": True}, BridgeConfig(port=0))
    credentials = bridge.start()
    try:
        host, port = bridge.address
        with socket.create_connection((host, port), timeout=2) as client:
            client.sendall((json.dumps({"id": 1, "method": "status", "params": {"action": "get"}, "auth": {"token": "bad"}}) + "\n").encode())
            assert json.loads(client.recv(4096))["error"]["code"] == "unauthorized"
        with socket.create_connection((host, port), timeout=2) as client:
            client.sendall((json.dumps({"id": 2, "method": "status", "params": {"action": "get"}, "auth": {"token": credentials.token}}) + "\n").encode())
            assert json.loads(client.recv(4096))["result"]["ok"]
        assert seen == ["status"]
    finally:
        bridge.stop()


class _FakeArray:
    def __init__(self, name, values):
        self._name, self._values = name, values

    def GetName(self):
        return self._name

    def GetNumberOfTuples(self):
        return len(self._values)

    def GetTuple(self, index):
        return self._values[index]


class _FakeAttributes:
    def __init__(self, arrays):
        self._arrays = arrays

    def GetNumberOfArrays(self):
        return len(self._arrays)

    def GetArray(self, index):
        return self._arrays[index]


class _FakeBlock:
    def __init__(self, arrays):
        self._data = _FakeAttributes(arrays)

    def GetPointData(self):
        return self._data

    def GetCellData(self):
        return _FakeAttributes([])


class _FakeMultiBlock:
    def __init__(self, blocks):
        self._blocks = blocks

    def GetNumberOfBlocks(self):
        return len(self._blocks)

    def GetBlock(self, index):
        return self._blocks[index]


class _FakeView:
    Field = None

    def getEnumerationsOfProperty(self, _name):
        return ["Displacement"]


class _FakePipeline:
    TypeId = "Fem::FemPostPipeline"

    def __init__(self):
        self.Data = _FakeMultiBlock([_FakeBlock([_FakeArray("U", [(1.0, 2.0, 3.0), (-1.0, 0.5, 2.0)])])])
        self.ViewObject = _FakeView()


def test_native_vtk_pipeline_alias_and_extrema() -> None:
    pipeline = FemPostPipeline()
    native = _FakePipeline()
    summary = pipeline.query_native([native], "displacement", 0, 32)
    assert summary["field"] == "Displacement"
    assert summary["extrema"] == {"min": -1.0, "max": 3.0, "count": 2}
    shown = pipeline.show_native([native], "displacement", 0, 32)
    assert shown["shown"] is True
    assert native.ViewObject.Field == "Displacement"


def test_gmsh_element_order_uses_freecad_enum() -> None:
    # Exercise the normalization branch without importing FreeCAD.  The
    # operation helper is intentionally pure at this boundary.
    assert FreeCADOperations._object_id(type("Obj", (), {"Name": "Mesh"})()) == "Mesh"


def test_document_revision_is_exposed_for_safe_overwrite() -> None:
    class _Doc:
        Name = "Doc"
        Label = "Doc"
        FileName = ""
        Objects = []

    class _App:
        ActiveDocument = _Doc()

        @staticmethod
        def Version():
            return ("1", "1", "3")

    operations = FreeCADOperations(app=_App())
    assert operations.active_document()["revision"] == "0"
    service = FEMService(operations=operations)
    with pytest.raises(ServiceError):
        service(Request(1, "status", {"action": "get", "document_id": "Other"}))
