"""FreeCAD operation property mapping tests using native-API-shaped fakes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "addon"))

from FreeCADFEMMCP.operations import FreeCADOperations, OperationError  # noqa: E402


class _NativeDisplacement:
    _allowed = {
        "Name", "Label", "TypeId", "References",
        "xFree", "yFree", "zFree",
        "xDisplacement", "yDisplacement", "zDisplacement",
        "EnableAmplitude", "AmplitudeValues",
    }

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native displacement property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name, self.Label, self.TypeId = name, name, "Fem::ConstraintDisplacement"
        self.References = []
        self.EnableAmplitude = False
        self.AmplitudeValues = []


class _Analysis:
    Name = "Analysis"
    Label = "Analysis"
    TypeId = "Fem::FemAnalysis"

    def __init__(self):
        self.Group = []

    def addObject(self, obj):
        self.Group.append(obj)


class _ShapeElement:
    def __init__(self, shape_type: str, curve_type: str | None = None):
        self.ShapeType = shape_type
        if curve_type is not None:
            self.Curve = type("Curve", (), {"TypeId": curve_type})()


class _Shape:
    def __init__(self):
        self._elements = {
            "Vertex1": _ShapeElement("Vertex"),
            "Edge1": _ShapeElement("Edge", "Part::GeomLine"),
            "Face1": _ShapeElement("Face"),
            "Face2": _ShapeElement("Face"),
            "Solid1": _ShapeElement("Solid"),
        }
        self.Solids = [self._elements["Solid1"]]

    def getElement(self, name: str):
        if name not in self._elements:
            raise ValueError("subelement does not exist")
        return self._elements[name]


class _MismatchedShape(_Shape):
    def getElement(self, name: str):
        if name == "Face1":
            return _ShapeElement("Edge")
        return super().getElement(name)


class _Geometry:
    Name = "Geometry"
    Label = "Geometry"
    TypeId = "Part::Box"
    Shape = _Shape()


class _Document:
    def __init__(self):
        self.Objects = []
        self._objects = {}
        self.analysis = _Analysis()
        self.geometry = _Geometry()
        self.Objects.extend([self.analysis, self.geometry])
        self._objects.update({"Analysis": self.analysis, "Geometry": self.geometry})

    def getObject(self, name):
        return self._objects.get(name)


class _App:
    def __init__(self):
        self.ActiveDocument = _Document()

    @staticmethod
    def Version():
        return ("1", "1", "3")


class _ObjectsFem:
    @staticmethod
    def makeConstraintDisplacement(_doc, name):
        return _NativeDisplacement(name)


class _NativeDisplacementWithoutAmplitude(_NativeDisplacement):
    def __init__(self, name: str):
        self.Name, self.Label, self.TypeId = name, name, "Fem::ConstraintDisplacement"
        self.References = []


class _ObjectsFemWithoutAmplitude(_ObjectsFem):
    @staticmethod
    def makeConstraintDisplacement(_doc, name):
        return _NativeDisplacementWithoutAmplitude(name)


class _NativeSelfWeight:
    _allowed = {"Name", "Label", "TypeId", "GravityAcceleration", "GravityDirection"}

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native self-weight property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name, self.Label, self.TypeId = name, name, "Fem::ConstraintPython"


class _ObjectsFemWithSelfWeight(_ObjectsFem):
    @staticmethod
    def makeConstraintSelfWeight(_doc, name):
        return _NativeSelfWeight(name)


class _NativeRigidBody:
    _allowed = {
        "Name", "Label", "TypeId", "References", "ReferenceNode", "Displacement", "Rotation",
        "TranslationalModeX", "TranslationalModeY", "TranslationalModeZ",
        "RotationalModeX", "RotationalModeY", "RotationalModeZ",
        "ForceX", "ForceY", "ForceZ", "MomentX", "MomentY", "MomentZ",
        "EnableAmplitude", "AmplitudeValues",
    }

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native rigid-body property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name, self.Label, self.TypeId = name, name, "Fem::ConstraintRigidBody"
        self.References = []
        self.EnableAmplitude = False
        self.AmplitudeValues = []


class _ObjectsFemWithRigidBody(_ObjectsFem):
    @staticmethod
    def makeConstraintRigidBody(_doc, name):
        return _NativeRigidBody(name)


class _NativeCentrifugal:
    _allowed = {"Name", "Label", "TypeId", "References", "RotationAxis", "RotationFrequency"}

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native centrifugal property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name, self.Label, self.TypeId = name, name, "Fem::ConstraintPython"


class _ObjectsFemWithCentrifugal(_ObjectsFem):
    @staticmethod
    def makeConstraintCentrif(_doc, name):
        return _NativeCentrifugal(name)


def test_displacement_uses_freecad_11_native_property_names() -> None:
    app = _App()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFem)
    result = operations.add_constraint(
        "Analysis",
        "displacement",
        {
            "references": [{"object": "Geometry", "sub_element": "Face1"}],
            "x": 0.1,
            "y": -0.2,
            "z": 0.0,
            "xFree": False,
            "yFree": False,
            "zFree": False,
        },
    )

    native = next(item for item in app.ActiveDocument.analysis.Group if item.TypeId == "Fem::ConstraintDisplacement")
    assert result["kind"] == "displacement"
    assert native.xDisplacement == "0.1 m"
    assert native.yDisplacement == "-0.2 m"
    assert native.zDisplacement == "0.0 m"
    assert (native.xFree, native.yFree, native.zFree) == (False, False, False)
    assert not hasattr(native, "x")
    assert not hasattr(native, "y")
    assert not hasattr(native, "z")


def test_amplitude_is_written_as_native_calculix_rows() -> None:
    app = _App()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFem)
    operations.add_constraint(
        "Analysis",
        "displacement",
        {
            "references": [{"object": "Geometry", "sub_element": "Face1"}],
            "x": 0.1,
            "xFree": False,
            "amplitude": [
                {"time_s": 0.0, "scale": 1.0},
                {"time_s": 0.25, "scale": -0.5},
            ],
        },
    )
    native = next(item for item in app.ActiveDocument.analysis.Group if item.TypeId == "Fem::ConstraintDisplacement")
    assert native.EnableAmplitude is True
    assert native.AmplitudeValues == ["0, 1", "0.25, -0.5"]


def test_amplitude_requires_native_properties_and_does_not_add_object() -> None:
    app = _App()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithoutAmplitude)
    with pytest.raises(OperationError):
        operations.add_constraint(
            "Analysis",
            "displacement",
            {
                "references": [{"object": "Geometry", "sub_element": "Face1"}],
                "x": 0.1,
                "xFree": False,
                "amplitude": [{"time_s": 0.0, "scale": 1.0}, {"time_s": 1.0, "scale": 1.0}],
            },
        )
    assert not app.ActiveDocument.analysis.Group


def test_selfweight_is_global_and_does_not_require_references() -> None:
    app = _App()
    app.Vector = lambda x, y, z: (x, y, z)
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithSelfWeight)
    result = operations.add_constraint(
        "Analysis",
        "selfweight",
        {
            "references": [],
            "gravity_acceleration": 9.80665,
            "gravity_direction": [0.0, 0.0, -1.0],
        },
    )

    native = next(item for item in app.ActiveDocument.analysis.Group if item.TypeId == "Fem::ConstraintPython")
    assert result["kind"] == "selfweight"
    assert native.GravityAcceleration == "9.80665 m/s^2"
    assert native.GravityDirection == (0.0, 0.0, -1.0)


def test_remote_load_maps_si_vectors_to_native_rigid_body_properties() -> None:
    app = _App()
    app.Vector = lambda x, y, z: (x, y, z)
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithRigidBody)
    result = operations.add_remote_load(
        "Analysis",
        {
            "references": [{"object": "Geometry", "sub_element": "Face1"}],
            "reference_point_m": [1.0, 2.0, 3.0],
            "force_n": [10.0, 0.0, 0.0],
            "moment_n_m": [0.0, 0.0, 2.5],
        },
    )

    native = next(
        item for item in app.ActiveDocument.analysis.Group
        if item.TypeId == "Fem::ConstraintRigidBody"
    )
    assert result["kind"] == "remote_load"
    assert native.References == [(app.ActiveDocument.geometry, "Face1")]
    assert native.ReferenceNode == (1000.0, 2000.0, 3000.0)
    assert (native.TranslationalModeX, native.TranslationalModeY, native.TranslationalModeZ) == (
        "Load", "Free", "Free"
    )
    assert (native.RotationalModeX, native.RotationalModeY, native.RotationalModeZ) == (
        "Free", "Free", "Load"
    )
    assert (native.ForceX, native.ForceY, native.ForceZ) == ("10.0 N", "0.0 N", "0.0 N")
    assert (native.MomentX, native.MomentY, native.MomentZ) == (
        "0.0 N*m", "0.0 N*m", "2.5 N*m"
    )


def test_remote_load_maps_amplitude_rows() -> None:
    app = _App()
    app.Vector = lambda x, y, z: (x, y, z)
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithRigidBody)
    operations.add_remote_load(
        "Analysis",
        {
            "references": [{"object": "Geometry", "sub_element": "Face1"}],
            "reference_point_m": [0.0, 0.0, 0.0],
            "force_n": [1.0, 0.0, 0.0],
            "amplitude": [{"time_s": 0.0, "scale": 0.0}, {"time_s": 2.0, "scale": 1.25}],
        },
    )
    native = next(item for item in app.ActiveDocument.analysis.Group if item.TypeId == "Fem::ConstraintRigidBody")
    assert native.EnableAmplitude is True
    assert native.AmplitudeValues == ["0, 0", "2, 1.25"]


def test_remote_load_rejects_stale_or_mismatched_native_subelements() -> None:
    for subelement, shape in (("Face999", None), ("Face1", _MismatchedShape())):
        app = _App()
        app.Vector = lambda x, y, z: (x, y, z)
        if shape is not None:
            app.ActiveDocument.geometry.Shape = shape
        operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithRigidBody)
        try:
            operations.add_remote_load(
                "Analysis",
                {
                    "references": [{"object": "Geometry", "sub_element": subelement}],
                    "reference_point_m": [0.0, 0.0, 0.0],
                    "force_n": [1.0, 0.0, 0.0],
                },
            )
        except OperationError:
            pass
        else:
            raise AssertionError("invalid native subelement was accepted")
        assert not app.ActiveDocument.analysis.Group


def test_remote_displacement_uses_constraint_modes_and_rotation_vector() -> None:
    app = _App()
    app.Vector = lambda x, y, z: (x, y, z)
    app.Rotation = lambda axis, Radian=0.0: ("rotation", axis, Radian)
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithRigidBody)
    result = operations.add_remote_displacement(
        "Analysis",
        {
            "references": [{"object": "Geometry", "sub_element": "Face1"}],
            "reference_point_m": [1.0, 2.0, 3.0],
            "translation_m": [0.1, None, 0.0],
            "rotation_rad": [None, 0.2, None],
        },
    )

    native = next(
        item for item in app.ActiveDocument.analysis.Group
        if item.TypeId == "Fem::ConstraintRigidBody"
    )
    assert result["kind"] == "remote_displacement"
    assert native.ReferenceNode == (1000.0, 2000.0, 3000.0)
    assert native.Displacement == (100.0, 0.0, 0.0)
    assert native.Rotation[0] == "rotation"
    assert (native.TranslationalModeX, native.TranslationalModeY, native.TranslationalModeZ) == (
        "Constraint", "Free", "Constraint"
    )
    assert (native.RotationalModeX, native.RotationalModeY, native.RotationalModeZ) == (
        "Free", "Constraint", "Free"
    )
    assert not hasattr(native, "ForceX")
    assert not hasattr(native, "MomentX")


def test_remote_displacement_rejects_stale_or_mismatched_native_subelements() -> None:
    for subelement, shape in (("Face999", None), ("Face1", _MismatchedShape())):
        app = _App()
        app.Vector = lambda x, y, z: (x, y, z)
        app.Rotation = lambda axis, Radian=0.0: ("rotation", axis, Radian)
        if shape is not None:
            app.ActiveDocument.geometry.Shape = shape
        operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithRigidBody)
        try:
            operations.add_remote_displacement(
                "Analysis",
                {
                    "references": [{"object": "Geometry", "sub_element": subelement}],
                    "reference_point_m": [0.0, 0.0, 0.0],
                    "translation_m": [0.001, None, None],
                },
            )
        except OperationError:
            pass
        else:
            raise AssertionError("invalid native subelement was accepted")
        assert not app.ActiveDocument.analysis.Group


def test_centrifugal_load_maps_axis_frequency_and_solid_references() -> None:
    app = _App()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithCentrifugal)
    result = operations.add_centrifugal_load(
        "Analysis",
        {
            "references": [{"object": "Geometry", "sub_element": "Solid1"}],
            "rotation_axis": [{"object": "Geometry", "sub_element": "Edge1"}],
            "rotation_frequency_hz": 50.0,
        },
    )

    native = next(
        item for item in app.ActiveDocument.analysis.Group
        if item.TypeId == "Fem::ConstraintPython"
    )
    assert result["kind"] == "centrifugal"
    assert native.References == [(app.ActiveDocument.geometry, "Solid1")]
    assert native.RotationAxis == [(app.ActiveDocument.geometry, "Edge1")]
    assert native.RotationFrequency == "50.0 Hz"


def test_centrifugal_load_rejects_stale_or_mismatched_native_subelements() -> None:
    cases = (
        ("Solid999", "Edge1", _Shape()),
        ("Solid1", "Edge999", _Shape()),
    )
    for body_subelement, axis_subelement, shape in cases:
        app = _App()
        app.ActiveDocument.geometry.Shape = shape
        operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithCentrifugal)
        try:
            operations.add_centrifugal_load(
                "Analysis",
                {
                    "references": [{"object": "Geometry", "sub_element": body_subelement}],
                    "rotation_axis": [{"object": "Geometry", "sub_element": axis_subelement}],
                    "rotation_frequency_hz": 50.0,
                },
            )
        except OperationError:
            pass
        else:
            raise AssertionError("invalid native subelement was accepted")
        assert not app.ActiveDocument.analysis.Group

    app = _App()
    shape = _Shape()
    shape.Solids = [_ShapeElement("Face")]
    app.ActiveDocument.geometry.Shape = shape
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithCentrifugal)
    try:
        operations.add_centrifugal_load(
            "Analysis",
            {
                "references": [{"object": "Geometry", "sub_element": "Solid1"}],
                "rotation_axis": [{"object": "Geometry", "sub_element": "Edge1"}],
                "rotation_frequency_hz": 50.0,
            },
        )
    except OperationError:
        pass
    else:
        raise AssertionError("mismatched native solid was accepted")
    assert not app.ActiveDocument.analysis.Group
