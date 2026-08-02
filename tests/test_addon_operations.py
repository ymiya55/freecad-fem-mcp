"""FreeCAD operation property mapping tests using native-API-shaped fakes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "addon"))

from FreeCADFEMMCP.operations import FreeCADOperations, OperationError  # noqa: E402


class _NativeDisplacement:
    _allowed = {
        "Name", "Label", "TypeId", "References",
        "xFree", "yFree", "zFree",
        "xDisplacement", "yDisplacement", "zDisplacement",
    }

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native displacement property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name, self.Label, self.TypeId = name, name, "Fem::ConstraintDisplacement"
        self.References = []


class _Analysis:
    Name = "Analysis"
    Label = "Analysis"
    TypeId = "Fem::FemAnalysis"

    def __init__(self):
        self.Group = []

    def addObject(self, obj):
        self.Group.append(obj)


class _ShapeElement:
    def __init__(self, shape_type: str):
        self.ShapeType = shape_type


class _Shape:
    def __init__(self):
        self._elements = {
            "Vertex1": _ShapeElement("Vertex"),
            "Edge1": _ShapeElement("Edge"),
            "Face1": _ShapeElement("Face"),
            "Face2": _ShapeElement("Face"),
        }

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
        "Name", "Label", "TypeId", "References", "ReferenceNode",
        "TranslationalModeX", "TranslationalModeY", "TranslationalModeZ",
        "RotationalModeX", "RotationalModeY", "RotationalModeZ",
        "ForceX", "ForceY", "ForceZ", "MomentX", "MomentY", "MomentZ",
    }

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native rigid-body property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name, self.Label, self.TypeId = name, name, "Fem::ConstraintRigidBody"
        self.References = []


class _ObjectsFemWithRigidBody(_ObjectsFem):
    @staticmethod
    def makeConstraintRigidBody(_doc, name):
        return _NativeRigidBody(name)


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
