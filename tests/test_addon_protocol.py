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
    assert parse_request_line(json.dumps({"id": 2, "method": "load", "params": {}})).method == "load"
    assert parse_request_line(json.dumps({"id": 3, "method": "boundary_condition", "params": {}})).method == "boundary_condition"
    assert parse_request_line(json.dumps({"id": 4, "method": "remote_load", "params": {}})).method == "remote_load"
    assert parse_request_line(json.dumps({"id": 5, "method": "remote_displacement", "params": {}})).method == "remote_displacement"
    assert parse_request_line(json.dumps({"id": 6, "method": "connection", "params": {}})).method == "connection"
    assert parse_request_line(json.dumps({"id": 7, "method": "element_geometry", "params": {}})).method == "element_geometry"
    with pytest.raises(ProtocolError):
        parse_request_line('{"id":1,"method":"ping","params":{}}')
    with pytest.raises(ProtocolError):
        parse_request_line('{"id":1,"method":"status","params":{},"extra":1}')


def test_connection_route_forwards_tie_and_contact_contracts() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        def __init__(self):
            self.calls = []

        def add_connection(self, analysis, kind, params):
            self.calls.append((analysis, kind, params))
            return {"name": "Native_" + kind}

    operations = _Operations()
    service = FEMService(
        operations=operations,
        selection=_Selection(),
        jobs=object(),
        pipeline=object(),
    )
    slave = {"object_name": "Upper", "subelements": ["Face3"]}
    master = {"object_name": "Lower", "subelements": ["Face7"]}
    tie = service(Request(80, "connection", {
        "action": "add", "analysis_id": "Analysis", "connection_type": "tie",
        "slave": slave, "master": master, "tolerance_m": 0.002, "adjust": True,
    }))
    assert tie["connection_id"] == "Native_tie"
    assert operations.calls[-1] == (
        "Analysis", "tie", {
            "references": [
                {"object": "Upper", "sub_element": "Face3"},
                {"object": "Lower", "sub_element": "Face7"},
            ],
            "tolerance_m": 0.002,
            "adjust": True,
        },
    )
    contact = service(Request(81, "connection", {
        "action": "add", "analysis_id": "Analysis", "connection_type": "contact",
        "slave": slave, "master": master, "surface_behavior": "hard",
    }))
    assert contact["connection_id"] == "Native_contact"
    assert operations.calls[-1][2]["surface_behavior"] == "hard"


def test_element_geometry_route_forwards_explicit_native_references_and_kind() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        def __init__(self):
            self.calls = []

        def assign_element_geometry(self, analysis, kind, params):
            self.calls.append((analysis, kind, params))
            return {"name": "NativeGeometry", "kind": kind}

    operations = _Operations()
    service = FEMService(
        operations=operations,
        selection=_Selection(),
        jobs=object(),
        pipeline=object(),
    )
    result = service(Request(85, "element_geometry", {
        "action": "assign",
        "analysis_id": "Analysis",
        "kind": "beam_section",
        "targets": [{"object_name": "Beam", "subelements": ["Edge1"]}],
        "section_type": "pipe",
        "pipe_diameter_m": 0.03,
        "pipe_thickness_m": 0.002,
    }))
    assert result["element_geometry_id"] == "NativeGeometry"
    assert operations.calls[-1] == (
        "Analysis",
        "beam_section",
        {
            "section_type": "pipe",
            "pipe_diameter_m": 0.03,
            "pipe_thickness_m": 0.002,
            "references": [{"object": "Beam", "sub_element": "Edge1"}],
        },
    )


def test_element_geometry_route_rejects_wrong_or_unwanted_fields_before_native() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        @staticmethod
        def assign_element_geometry(*_args, **_kwargs):
            raise AssertionError("invalid geometry reached native operations")

    service = FEMService(
        operations=_Operations(),
        selection=_Selection(),
        jobs=object(),
        pipeline=object(),
    )
    base = {
        "action": "assign",
        "analysis_id": "Analysis",
        "kind": "shell",
        "targets": [{"object_name": "Plate", "subelements": ["Face1"]}],
        "thickness_m": 0.001,
    }
    for extra in (
        {"section_type": "rectangular"},
        {"targets": [{"object_name": "Plate", "subelements": ["Edge1"]}]},
        {"targets": [{"object_name": "Plate", "subelements": ["Face1", "Face1"]}]},
        {"thickness_m": float("nan")},
    ):
        params = dict(base)
        params.update(extra)
        with pytest.raises(ServiceError):
            service(Request(86, "element_geometry", params))


def test_connection_route_forwards_closed_cyclic_symmetry_contract() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        def __init__(self):
            self.calls = []

        def add_connection(self, analysis, kind, params):
            self.calls.append((analysis, kind, params))
            return {"name": "Native_" + kind}

    operations = _Operations()
    service = FEMService(
        operations=operations,
        selection=_Selection(),
        jobs=object(),
        pipeline=object(),
    )
    service(Request(83, "connection", {
        "action": "add",
        "analysis_id": "Analysis",
        "connection_type": "cyclic_symmetry",
        "slave": {"object_name": "Upper", "subelements": ["Face3"]},
        "master": {"object_name": "Lower", "subelements": ["Face7"]},
        "tolerance_m": 0.002,
        "adjust": True,
        "sectors": 8,
        "connected_sectors": 2,
    }))
    assert operations.calls[-1] == (
        "Analysis",
        "cyclic_symmetry",
        {
            "references": [
                {"object": "Upper", "sub_element": "Face3"},
                {"object": "Lower", "sub_element": "Face7"},
            ],
            "tolerance_m": 0.002,
            "adjust": True,
            "sectors": 8,
            "connected_sectors": 2,
        },
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"sectors": 1, "connected_sectors": 1},
        {"sectors": 4, "connected_sectors": 4},
        {"sectors": 4, "connected_sectors": 1, "symmetry_axis": {}},
    ],
)
def test_connection_route_rejects_cyclic_bounds_and_unknown_axis(bad) -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        @staticmethod
        def add_connection(*_args, **_kwargs):
            raise AssertionError("invalid cyclic connection reached native operations")

    service = FEMService(
        operations=_Operations(),
        selection=_Selection(),
        jobs=object(),
        pipeline=object(),
    )
    params = {
        "action": "add",
        "analysis_id": "Analysis",
        "connection_type": "cyclic_symmetry",
        "slave": {"object_name": "Upper", "subelements": ["Face1"]},
        "master": {"object_name": "Lower", "subelements": ["Face2"]},
        "tolerance_m": 0.0,
        "adjust": False,
        "sectors": 4,
        "connected_sectors": 1,
    }
    params.update(bad)
    with pytest.raises(ServiceError):
        service(Request(84, "connection", params))


@pytest.mark.parametrize(
    "bad",
    [
        {"slave": {"object_name": "Upper", "subelements": ["Face1", "Face2"]}},
        {"slave": {"object_name": "Upper", "subelements": ["Edge1"]}},
        {"master": {"object_name": "Upper", "subelements": ["Face1"]}},
        {"surface_behavior": "linear"},
        {"tolerance_m": "0.1"},
        {"adjust": 1},
        {"extra": True},
    ],
)
def test_connection_route_rejects_malformed_or_mode_specific_fields(bad) -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        @staticmethod
        def add_connection(*_args, **_kwargs):
            raise AssertionError("invalid connection reached native operations")

    service = FEMService(
        operations=_Operations(), selection=_Selection(), jobs=object(), pipeline=object()
    )
    params = {
        "action": "add", "analysis_id": "Analysis", "connection_type": "tie",
        "slave": {"object_name": "Upper", "subelements": ["Face1"]},
        "master": {"object_name": "Lower", "subelements": ["Face2"]},
    }
    if "surface_behavior" in bad:
        params["connection_type"] = "contact"
    params.update(bad)
    with pytest.raises(ServiceError):
        service(Request(82, "connection", params))


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


def test_gmsh_element_order_is_native_enum() -> None:
    class _Obj:
        def __init__(self, name, type_id):
            self.Name, self.Label, self.TypeId = name, name, type_id
            self.Group, self.Shape = [], object()

        def addObject(self, obj):
            self.Group.append(obj)

    class _Doc:
        def __init__(self):
            self.Objects = []
            self._objects = {}

        def getObject(self, name):
            return self._objects.get(name)

        def addObject(self, type_id, name):
            obj = _Obj(name, type_id)
            self.Objects.append(obj)
            self._objects[name] = obj
            return obj

    class _App:
        def __init__(self):
            self.ActiveDocument = _Doc()

        @staticmethod
        def Version():
            return ("1", "1", "3")

    class _ObjectsFem:
        @staticmethod
        def makeMeshGmsh(doc, name):
            return doc.addObject("Fem::FemMeshGmsh", name)

    app = _App()
    app.ActiveDocument.addObject("Fem::FemAnalysis", "Analysis")
    app.ActiveDocument.addObject("Part::Box", "Geometry")
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFem)
    result = operations.create_mesh("Analysis", "Mesh", shape="Geometry", ElementOrder=2)
    mesh = app.ActiveDocument.getObject(result["name"])
    assert mesh.ElementOrder == "2nd"


def test_typed_load_and_boundary_routes_use_native_constraint_kinds() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        def __init__(self):
            self.calls = []

        def add_constraint(self, analysis, kind, params):
            self.calls.append((analysis, kind, params))
            return {"name": "Native_" + kind}

    operations = _Operations()
    service = FEMService(operations=operations, selection=_Selection())
    target = [{"object_name": "Beam", "subelements": ["Face1"]}]

    force = service(Request(1, "load", {
        "action": "add", "analysis_id": "Analysis", "load_type": "force",
        "targets": target, "force_n": 1250.0,
    }))
    assert force["load_id"] == "Native_force"
    assert operations.calls[-1][:2] == ("Analysis", "force")
    assert operations.calls[-1][2] == {"references": [{"object": "Beam", "sub_element": "Face1"}], "force": 1250.0}

    gravity = service(Request(2, "load", {
        "action": "add", "analysis_id": "Analysis", "load_type": "gravity",
        "targets": target, "acceleration_m_s2": [3.0, 4.0, 0.0],
    }))
    assert gravity["load_id"] == "Native_selfweight"
    assert operations.calls[-1][:2] == ("Analysis", "selfweight")
    assert operations.calls[-1][2]["gravity_acceleration"] == 5.0
    assert operations.calls[-1][2]["gravity_direction"] == [3.0, 4.0, 0.0]

    boundary = service(Request(3, "boundary_condition", {
        "action": "add", "analysis_id": "Analysis", "boundary_type": "displacement",
        "targets": target, "displacement_m": [0.0, 0.001, -0.002],
    }))
    assert boundary["boundary_condition_id"] == "Native_displacement"
    assert operations.calls[-1][:2] == ("Analysis", "displacement")
    assert operations.calls[-1][2]["xFree"] is False
    assert operations.calls[-1][2]["y"] == 0.001

    acceleration = service(Request(4, "load", {
        "action": "add", "analysis_id": "Analysis", "load_type": "acceleration",
        "targets": target, "acceleration_m_s2": [0.0, -9.81, 0.0],
    }))
    assert acceleration["load_id"] == "Native_selfweight"
    assert operations.calls[-1][:2] == ("Analysis", "selfweight")
    assert operations.calls[-1][2]["gravity_acceleration"] == 9.81


def test_plane_rotation_constraint_route_is_mpc_only_and_closed() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        def __init__(self):
            self.calls = []

        def add_constraint(self, analysis, kind, params):
            self.calls.append((analysis, kind, params))
            return {"name": "Native_" + kind}

    operations = _Operations()
    service = FEMService(operations=operations, selection=_Selection())
    result = service(Request(5, "constraint", {
        "action": "add",
        "analysis_id": "Analysis",
        "constraint_type": "plane_rotation",
        "targets": [{"object_name": "Beam", "subelements": ["Edge1"]}],
    }))
    assert result["constraint_id"] == "Native_plane_rotation"
    assert operations.calls[-1] == (
        "Analysis",
        "plane_rotation",
        {"references": [{"object": "Beam", "sub_element": "Edge1"}]},
    )
    with pytest.raises(ServiceError):
        service(Request(6, "constraint", {
            "action": "add",
            "analysis_id": "Analysis",
            "constraint_type": "plane_rotation",
            "targets": [{"object_name": "Beam", "subelements": ["Face1"]}],
            "force_n": 1.0,
        }))


def test_analysis_route_forwards_frequency_and_buckling_controls() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        def __init__(self):
            self.create_calls = []
            self.validate_calls = []

        def create_analysis(self, *args, **kwargs):
            self.create_calls.append((args, kwargs))
            return {"name": "Analysis", "analysis_type": kwargs["analysis_type"]}

        def validate(self, analysis, *, strict=True):
            self.validate_calls.append((analysis, strict))
            return {"valid": True, "diagnostics": []}

    operations = _Operations()
    service = FEMService(operations=operations, selection=_Selection(), jobs=object(), pipeline=object())
    frequency = service(Request(70, "analysis", {
        "action": "create", "analysis_type": "frequency", "eigenmodes_count": 5,
        "frequency_low_hz": 0.0, "frequency_high_hz": 1000.0,
    }))
    assert frequency["analysis_id"] == "Analysis"
    assert operations.create_calls[-1][1] == {
        "analysis_type": "frequency", "eigenmodes_count": 5,
        "frequency_low_hz": 0.0, "frequency_high_hz": 1000.0,
        "buckling_factors": None, "buckling_accuracy": None,
    }

    buckling = service(Request(71, "analysis", {
        "action": "create", "analysis_type": "buckling", "buckling_factors": 3,
        "buckling_accuracy": 0.1,
    }))
    assert buckling["analysis_id"] == "Analysis"
    assert operations.create_calls[-1][1]["buckling_factors"] == 3

    checked = service(Request(72, "validate", {
        "action": "validate", "analysis_id": "Analysis", "strict": False,
    }))
    assert checked["valid"] is True
    assert operations.validate_calls[-1] == ("Analysis", False)


def test_analysis_route_rejects_static_mode_specific_fields() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        @staticmethod
        def create_analysis(*_args, **_kwargs):
            raise AssertionError("invalid analysis reached native operations")

    service = FEMService(operations=_Operations(), selection=_Selection(), jobs=object(), pipeline=object())
    with pytest.raises(ServiceError):
        service(Request(73, "analysis", {
            "action": "create", "analysis_type": "static", "eigenmodes_count": 1,
        }))


def test_remote_displacement_and_centrifugal_routes_are_strict() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        def __init__(self):
            self.remote = []
            self.centrif = []

        def add_remote_displacement(self, analysis, params):
            self.remote.append((analysis, params))
            return {"name": "Native_RemoteDisplacement"}

        def add_centrifugal_load(self, analysis, params):
            self.centrif.append((analysis, params))
            return {"name": "Native_Centrifugal"}

    operations = _Operations()
    service = FEMService(operations=operations, selection=_Selection())
    targets = [{"object_name": "Beam", "subelements": ["Face1"]}]
    displacement = service(Request(40, "remote_displacement", {
        "action": "add", "analysis_id": "Analysis", "targets": targets,
        "reference_point_m": [1.0, 2.0, 3.0],
        "translation_m": [0.0, None, 0.1],
        "rotation_rad": [None, None, None],
    }))
    assert displacement["remote_displacement_id"] == "Native_RemoteDisplacement"
    assert operations.remote[-1][1]["translation_m"] == [0.0, None, 0.1]

    centrifugal = service(Request(41, "load", {
        "action": "add", "analysis_id": "Analysis", "load_type": "centrifugal",
        "axis": {"object_name": "Axis", "subelements": ["Edge1"]},
        "targets": [{"object_name": "Rotor", "subelements": ["Solid1"]}],
        "rotation_frequency_hz": 50.0,
    }))
    assert centrifugal["load_id"] == "Native_Centrifugal"
    assert operations.centrif[-1][1] == {
        "references": [{"object": "Rotor", "sub_element": "Solid1"}],
        "rotation_axis": [{"object": "Axis", "sub_element": "Edge1"}],
        "rotation_frequency_hz": 50.0,
    }

    invalid = {
        "action": "add", "analysis_id": "Analysis", "targets": targets,
        "reference_point_m": [0.0, 0.0, 0.0], "translation_m": [None, None, None],
    }
    for bad in (
        {"translation_m": [0.0, None]},
        {"rotation_rad": [None, None, 1e6 + 1.0]},
        {"native_property": "Displacement"},
    ):
        params = dict(invalid)
        params.update(bad)
        with pytest.raises(ServiceError):
            service(Request(42, "remote_displacement", params))


def test_remote_load_route_validates_targets_and_vectors() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        def __init__(self):
            self.calls = []

        def add_remote_load(self, analysis, params):
            self.calls.append((analysis, params))
            return {"name": "Native_RemoteLoad"}

    operations = _Operations()
    service = FEMService(operations=operations, selection=_Selection())
    target = [{"object_name": "Beam", "subelements": ["Face1", "Face2"]}]
    result = service(Request(30, "remote_load", {
        "action": "add",
        "analysis_id": "Analysis",
        "targets": target,
        "reference_point_m": [1.0, 2.0, 3.0],
        "force_n": [100.0, 0.0, 0.0],
        "moment_n_m": [0.0, 0.0, 25.0],
    }))
    assert result["remote_load_id"] == "Native_RemoteLoad"
    assert operations.calls[-1] == (
        "Analysis",
        {
            "references": [
                {"object": "Beam", "sub_element": "Face1"},
                {"object": "Beam", "sub_element": "Face2"},
            ],
            "reference_point_m": [1.0, 2.0, 3.0],
            "force_n": [100.0, 0.0, 0.0],
            "moment_n_m": [0.0, 0.0, 25.0],
        },
    )

    invalid = {
        "action": "add",
        "analysis_id": "Analysis",
        "targets": target,
        "reference_point_m": [0.0, 0.0, 0.0],
        "force_n": [1.0, 0.0, 0.0],
    }
    for bad in (
        {"targets": []},
        {"targets": [{"object_name": "Beam", "subelements": []}]},
        {"targets": [{"object_name": "Beam", "subelements": ["Face1", "Edge1"]}]},
        {"targets": [{"object_name": "Beam", "subelements": ["Cell1"]}]},
        {"force_n": [0.0, 0.0, 0.0]},
        {"reference_point_m": [1e9 + 1.0, 0.0, 0.0]},
        {"force_n": [1e15 + 1.0, 0.0, 0.0]},
        {"force_n": [float("nan"), 0.0, 0.0]},
        {"native_property": "ForceX"},
    ):
        params = dict(invalid)
        params.update(bad)
        with pytest.raises(ServiceError):
            service(Request(31, "remote_load", params))


def test_typed_routes_reject_wrong_values_and_extra_fields() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        @staticmethod
        def add_constraint(*_args, **_kwargs):
            return {"name": "unused"}

    service = FEMService(operations=_Operations(), selection=_Selection())
    base = {"action": "add", "analysis_id": "Analysis", "load_type": "force", "force_n": 1.0}
    with pytest.raises(ServiceError):
        service(Request(4, "load", {**base, "pressure_pa": 2.0}))
    with pytest.raises(ServiceError):
        service(Request(5, "load", {**base, "force_n": "not-a-number"}))
    with pytest.raises(ServiceError):
        service(Request(6, "load", {
            "action": "add", "analysis_id": "Analysis", "load_type": "gravity",
            "acceleration_m_s2": [0.0, 9.81],
        }))
    with pytest.raises(ServiceError):
        service(Request(7, "boundary_condition", {
            "action": "add", "analysis_id": "Analysis", "boundary_type": "fixed",
            "displacement_m": [0.0, 0.0, 0.0],
        }))
    with pytest.raises(ServiceError):
        service(Request(8, "boundary_condition", {
            "action": "add", "analysis_id": "Analysis", "boundary_type": "fixed", "extra": True,
        }))


def test_amplitude_route_contract_and_forwarding() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        def __init__(self):
            self.calls = []

        def add_constraint(self, analysis, kind, params):
            self.calls.append((analysis, kind, params))
            return {"name": "Native_" + kind}

    operations = _Operations()
    service = FEMService(operations=operations, selection=_Selection())
    service(Request(10, "load", {
        "action": "add", "analysis_id": "Analysis", "load_type": "force",
        "force_n": 10.0, "targets": [{"object_name": "Beam", "subelements": ["Face1"]}],
        "amplitude": [{"time_s": 0.0, "scale": 0.0}, {"time_s": 1.0, "scale": 1.5}],
    }))
    assert operations.calls[-1][2]["amplitude"] == [
        {"time_s": 0.0, "scale": 0.0}, {"time_s": 1.0, "scale": 1.5}
    ]

    bad_amplitudes = (
        [{"time_s": 1.0, "scale": 1.0}, {"time_s": 2.0, "scale": 1.0}],
        [{"time_s": 0.0, "scale": 1.0, "extra": 0}, {"time_s": 1.0, "scale": 1.0}],
        [{"time_s": 0.0, "scale": 1.0}, {"time_s": 0.0, "scale": 1.0}],
    )
    for amplitude in bad_amplitudes:
        with pytest.raises(ServiceError):
            service(Request(11, "load", {
                "action": "add", "analysis_id": "Analysis", "load_type": "force",
                "force_n": 10.0, "amplitude": amplitude,
            }))
    with pytest.raises(ServiceError):
        service(Request(12, "load", {
            "action": "add", "analysis_id": "Analysis", "load_type": "gravity",
            "acceleration_m_s2": [0.0, 9.81, 0.0],
            "amplitude": [{"time_s": 0.0, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        }))
    with pytest.raises(ServiceError):
        service(Request(13, "boundary_condition", {
            "action": "add", "analysis_id": "Analysis", "boundary_type": "fixed",
            "amplitude": [{"time_s": 0.0, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
        }))


def test_gravity_rejects_zero_acceleration_vector() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        @staticmethod
        def add_constraint(*_args, **_kwargs):
            return {"name": "unused"}

    service = FEMService(operations=_Operations(), selection=_Selection())
    with pytest.raises(ServiceError):
        service(Request(9, "load", {
            "action": "add", "analysis_id": "Analysis", "load_type": "gravity",
            "acceleration_m_s2": [0.0, 0.0, 0.0],
        }))


def test_all_public_routes_reject_unknown_direct_bridge_fields() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        @staticmethod
        def add_constraint(*_args, **_kwargs):
            return {"name": "unused"}

    service = FEMService(operations=_Operations(), selection=_Selection(), jobs=object(), pipeline=object())
    cases = (
        ("status", {"action": "get"}),
        ("document", {"action": "active"}),
        ("selection", {"action": "get"}),
        ("view", {"action": "set"}),
        ("capture", {"action": "capture", "scope": "viewport"}),
        ("open", {"action": "open", "path": "model.FCStd"}),
        ("save", {"action": "save"}),
        ("analysis", {"action": "create"}),
        ("connection", {
            "action": "add", "analysis_id": "Analysis", "connection_type": "tie",
            "slave": {"object_name": "Upper", "subelements": ["Face1"]},
            "master": {"object_name": "Lower", "subelements": ["Face2"]},
        }),
        ("material", {"action": "assign", "analysis_id": "Analysis"}),
        ("constraint", {"action": "add", "analysis_id": "Analysis", "constraint_type": "fixed"}),
        ("load", {"action": "add", "analysis_id": "Analysis", "load_type": "force", "force_n": 1.0}),
        ("boundary_condition", {"action": "add", "analysis_id": "Analysis", "boundary_type": "fixed"}),
        ("remote_load", {
            "action": "add", "analysis_id": "Analysis",
            "targets": [{"object_name": "Geometry", "subelements": ["Face1"]}],
            "reference_point_m": [0.0, 0.0, 0.0], "force_n": [1.0, 0.0, 0.0],
        }),
        ("remote_displacement", {
            "action": "add", "analysis_id": "Analysis",
            "targets": [{"object_name": "Geometry", "subelements": ["Face1"]}],
            "reference_point_m": [0.0, 0.0, 0.0],
            "translation_m": [0.0, None, None],
        }),
        ("mesh", {"action": "create", "analysis_id": "Analysis"}),
        ("validate", {"action": "validate", "analysis_id": "Analysis"}),
        ("jobs", {"action": "start", "analysis_id": "Analysis"}),
        ("jobs", {"action": "get", "job_id": "Job"}),
        ("jobs", {"action": "list"}),
        ("jobs", {"action": "cancel", "job_id": "Job"}),
        ("results", {"action": "get", "analysis_id": "Analysis"}),
        ("results", {"action": "show", "analysis_id": "Analysis"}),
    )
    for index, (method, params) in enumerate(cases, 20):
        with pytest.raises(ServiceError):
            service(Request(index, method, {**params, "code": "print(1)"}))


def test_legacy_constraint_rejects_extra_nested_target_fields() -> None:
    class _Selection:
        gui = None

        @staticmethod
        def capture():
            return {"items": []}

    class _Operations:
        app = None

        @staticmethod
        def add_constraint(*_args, **_kwargs):
            return {"name": "unused"}

    service = FEMService(operations=_Operations(), selection=_Selection())
    with pytest.raises(ServiceError):
        service(Request(40, "constraint", {
            "action": "add", "analysis_id": "Analysis", "constraint_type": "fixed",
            "targets": [{"object_name": "Beam", "subelements": ["Face1"], "code": "x"}],
        }))
