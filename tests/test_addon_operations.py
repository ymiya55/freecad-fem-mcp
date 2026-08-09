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


class _NativeSolverForAnalysis:
    """Closed native-shaped solver fake used to exercise mode properties."""

    _allowed = {
        "Name", "Label", "TypeId", "AnalysisType", "EigenmodesCount",
        "EigenmodeLow", "EigenmodeHigh", "BucklingFactors", "BucklingAccuracy",
        "GeometricalNonlinearity", "MaterialNonlinearity",
    }

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native solver property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name, self.Label, self.TypeId = name, name, "Fem::SolverCalculiX"
        self.AnalysisType = "static"
        self.EigenmodesCount = 0
        self.EigenmodeLow = "0 Hz"
        self.EigenmodeHigh = "0 Hz"
        self.BucklingFactors = 0
        self.BucklingAccuracy = 0.0
        self.GeometricalNonlinearity = "linear"
        self.MaterialNonlinearity = "linear"


class _NativeAnalysisForCreate:
    TypeId = "Fem::FemAnalysis"

    def __init__(self, name: str):
        self.Name = self.Label = name
        self.Group = []

    def addObject(self, obj):
        self.Group.append(obj)


class _AnalysisDocument:
    def __init__(self, solver_factory=_NativeSolverForAnalysis):
        self.Name = "Doc"
        self.Objects = []
        self._objects = {}
        self._solver_factory = solver_factory
        self.transaction_events = []

    def getObject(self, name):
        return self._objects.get(name)

    def addObject(self, type_id, name):
        if type_id == "Fem::FemAnalysis":
            obj = _NativeAnalysisForCreate(name)
        elif type_id == "Fem::SolverCalculiX":
            obj = self._solver_factory(name)
        else:
            obj = type("NativeObject", (), {"Name": name, "Label": name, "TypeId": type_id})()
        self.Objects.append(obj)
        self._objects[name] = obj
        return obj

    def openTransaction(self, label):
        self.transaction_events.append(("open", label))

    def commitTransaction(self):
        self.transaction_events.append(("commit",))

    def abortTransaction(self):
        self.transaction_events.append(("abort",))


class _ObjectsFemForAnalysis:
    @staticmethod
    def makeAnalysis(doc, name):
        return doc.addObject("Fem::FemAnalysis", name)

    @staticmethod
    def makeSolverCalculiX(doc, name):
        return doc.addObject("Fem::SolverCalculiX", name)


class _AnalysisApp:
    def __init__(self, solver_factory=_NativeSolverForAnalysis):
        self.ActiveDocument = _AnalysisDocument(solver_factory)

    @staticmethod
    def Version():
        return ("1", "1", "3")


class _NativeConnectionSolver:
    TypeId = "Fem::SolverCalculiX"
    AnalysisType = "static"


class _NativeTie:
    _allowed = {
        "Name", "Label", "TypeId", "References", "Tolerance", "Adjust", "CyclicSymmetry",
    }

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native tie property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name = self.Label = name
        self.TypeId = "Fem::ConstraintTie"
        self.References = []
        self.Tolerance = 0.0
        self.Adjust = False
        self.CyclicSymmetry = False


class _NativeContact:
    _allowed = {
        "Name", "Label", "TypeId", "References", "SurfaceBehavior", "Friction",
        "EnableThermalContact",
    }

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native contact property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name = self.Label = name
        self.TypeId = "Fem::ConstraintContact"
        self.References = []
        self.SurfaceBehavior = "Hard"
        self.Friction = False
        self.EnableThermalContact = False


class _ConnectionAnalysis:
    TypeId = "Fem::FemAnalysis"

    def __init__(self, name: str = "Analysis"):
        self.Name = self.Label = name
        self.Group = [_NativeConnectionSolver()]

    def addObject(self, obj):
        self.Group.append(obj)


class _ConnectionDocument:
    Name = "Doc"

    def __init__(self):
        self.analysis = _ConnectionAnalysis()
        self.geometry = _Geometry()
        self.Objects = [self.analysis, self.geometry]
        self._objects = {"Analysis": self.analysis, "Geometry": self.geometry}
        self.transaction_events = []

    def getObject(self, name):
        return self._objects.get(name)

    def openTransaction(self, label):
        self.transaction_events.append(("open", label))

    def commitTransaction(self):
        self.transaction_events.append(("commit",))

    def abortTransaction(self):
        self.transaction_events.append(("abort",))


class _ConnectionApp:
    def __init__(self):
        self.ActiveDocument = _ConnectionDocument()

    @staticmethod
    def Version():
        return ("1", "1", "3")


class _ObjectsFemWithConnections:
    @staticmethod
    def makeConstraintTie(_doc, name):
        return _NativeTie(name)

    @staticmethod
    def makeConstraintContact(_doc, name):
        return _NativeContact(name)


def _analysis_solver(app: _AnalysisApp):
    return next(item for item in app.ActiveDocument.Objects if item.TypeId == "Fem::SolverCalculiX")


def _connection_operations(objects_fem=_ObjectsFemWithConnections):
    app = _ConnectionApp()
    return app, FreeCADOperations(app=app, objects_fem=objects_fem)


def _connection_refs(*faces):
    return [
        {"object": "Geometry", "sub_element": face}
        for face in faces
    ]


def test_tie_connection_maps_native_references_in_slave_master_order() -> None:
    app, operations = _connection_operations()
    result = operations.add_connection(
        "Analysis",
        "tie",
        {"references": _connection_refs("Face1", "Face2"), "tolerance_m": 0.25, "adjust": True},
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert result["kind"] == "tie"
    assert native.TypeId == "Fem::ConstraintTie"
    assert native.References == [
        (app.ActiveDocument.geometry, "Face1"),
        (app.ActiveDocument.geometry, "Face2"),
    ]
    assert native.Tolerance == 250.0
    assert native.Adjust is True
    assert native.CyclicSymmetry is False


def test_contact_connection_maps_hard_frictionless_native_properties() -> None:
    app, operations = _connection_operations()
    result = operations.add_connection(
        "Analysis",
        "contact",
        {"references": _connection_refs("Face2", "Face1"), "surface_behavior": "hard"},
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert result["kind"] == "contact"
    assert native.References == [
        (app.ActiveDocument.geometry, "Face2"),
        (app.ActiveDocument.geometry, "Face1"),
    ]
    assert native.SurfaceBehavior == "Hard"
    assert native.Friction is False
    assert native.EnableThermalContact is False


@pytest.mark.parametrize(
    "references",
    [
        _connection_refs("Face1", "Face1"),
        _connection_refs("Face1", "Face999"),
        _connection_refs("Face1", "Edge1"),
        _connection_refs("Face01", "Face2"),
    ],
)
def test_connection_rejects_duplicate_stale_or_non_face_references(references) -> None:
    _app, operations = _connection_operations()
    with pytest.raises(OperationError):
        operations.add_connection(
            "Analysis", "tie", {"references": references, "tolerance_m": 0.0}
        )


def test_connection_requires_static_solver_mode() -> None:
    app, operations = _connection_operations()
    app.ActiveDocument.analysis.Group[0].AnalysisType = "frequency"
    with pytest.raises(OperationError):
        operations.add_connection(
            "Analysis", "tie", {
                "references": _connection_refs("Face1", "Face2"),
                "tolerance_m": 0.0,
                "adjust": False,
            }
        )
    assert len(app.ActiveDocument.analysis.Group) == 1


def test_connection_missing_factory_or_property_aborts_transaction() -> None:
    app, operations = _connection_operations(objects_fem=object())
    with pytest.raises(OperationError):
        operations.add_connection(
            "Analysis", "tie", {
                "references": _connection_refs("Face1", "Face2"),
                "tolerance_m": 0.0,
                "adjust": False,
            }
        )
    assert app.ActiveDocument.transaction_events[-1][0] == "abort"
    assert len(app.ActiveDocument.analysis.Group) == 1

    class _TieWithoutCyclic(_NativeTie):
        def __init__(self, name):
            super().__init__(name)
            object.__delattr__(self, "CyclicSymmetry")

    class _ObjectsFemWithoutCyclic:
        @staticmethod
        def makeConstraintTie(_doc, name):
            return _TieWithoutCyclic(name)

    app, operations = _connection_operations(objects_fem=_ObjectsFemWithoutCyclic())
    with pytest.raises(OperationError):
        operations.add_connection(
            "Analysis", "tie", {
                "references": _connection_refs("Face1", "Face2"),
                "tolerance_m": 0.0,
                "adjust": False,
            }
        )
    assert app.ActiveDocument.transaction_events[-1][0] == "abort"
    assert len(app.ActiveDocument.analysis.Group) == 1


class _BoundaryObjectsFem(_ObjectsFemWithConnections):
    @staticmethod
    def makeConstraintDisplacement(_doc, name):
        return _NativeDisplacement(name)

def _boundary_operations():
    app = _ConnectionApp()
    return app, FreeCADOperations(app=app, objects_fem=_BoundaryObjectsFem)


def test_pin_and_roller_use_native_displacement_dof_presets() -> None:
    app, operations = _boundary_operations()
    pin = operations.add_constraint(
        "Analysis", "pin", {"references": _connection_refs("Face1")}
    )
    pin_obj = app.ActiveDocument.analysis.Group[-1]
    assert pin["kind"] == "pin"
    assert (pin_obj.xFree, pin_obj.yFree, pin_obj.zFree) == (False, False, False)

    roller = operations.add_constraint(
        "Analysis", "roller", {"references": _connection_refs("Face2"), "axis": "z"}
    )
    roller_obj = app.ActiveDocument.analysis.Group[-1]
    assert roller["kind"] == "roller"
    assert (roller_obj.xFree, roller_obj.yFree, roller_obj.zFree) == (True, True, False)


@pytest.mark.parametrize(
    "field",
    [
        "xFree", "yFree", "zFree", "x", "xDisplacement",
        "rotxFree", "rotyFree", "rotzFree", "rotx", "rotxDisplacement",
    ],
)
def test_pin_and_roller_reject_direct_dof_overrides(field: str) -> None:
    _app, operations = _boundary_operations()
    params = {"references": _connection_refs("Face1"), field: False}
    if field in {"x", "xDisplacement", "rotx", "rotxDisplacement"}:
        params[field] = 0.25
    with pytest.raises(OperationError, match="DOF fields"):
        operations.add_constraint("Analysis", "pin", params)
    with pytest.raises(OperationError, match="DOF fields"):
        roller_params = {
            "references": _connection_refs("Face1"),
            "axis": "x",
            field: params[field],
        }
        operations.add_constraint("Analysis", "roller", roller_params)


@pytest.mark.parametrize("subelement", ["Vertex1", "Edge1", "Face1", "Solid1"])
def test_boundary_accepts_only_live_native_shape_subelements(subelement: str) -> None:
    _app, operations = _boundary_operations()
    result = operations.add_constraint(
        "Analysis", "pin", {"references": _connection_refs(subelement)}
    )
    assert result["kind"] == "pin"


def test_boundary_preserves_explicit_whole_shape_reference() -> None:
    app, operations = _boundary_operations()
    result = operations.add_constraint(
        "Analysis", "pin", {"references": [{"object": "Geometry", "sub_element": ""}]}
    )
    assert result["kind"] == "pin"
    assert app.ActiveDocument.analysis.Group[-1].References == [(app.ActiveDocument.geometry, "")]


@pytest.mark.parametrize("subelement", ["Junk1", "Face999", "Face01"])
def test_boundary_rejects_forged_or_stale_shape_subelements(subelement: str) -> None:
    _app, operations = _boundary_operations()
    with pytest.raises(OperationError):
        operations.add_constraint(
            "Analysis", "roller", {"references": _connection_refs(subelement), "axis": "x"}
        )


def test_validate_reports_empty_reference_zero_dof_and_rigid_motion() -> None:
    app, operations = _boundary_operations()
    document = app.ActiveDocument
    document.analysis.Group.extend(
        [
            type(
                "Material",
                (),
                {
                    "Name": "Material",
                    "Label": "Material",
                    "TypeId": "App::MaterialObjectPython",
                    "Material": {"Density": "7850 kg/m^3"},
                },
            )(),
            type("Mesh", (), {"Name": "Mesh", "Label": "Mesh", "TypeId": "Fem::FemMeshGmsh"})(),
        ]
    )
    displacement = _NativeDisplacement("BadDisplacement")
    displacement.xFree = displacement.yFree = displacement.zFree = True
    displacement.EnableAmplitude = True
    displacement.AmplitudeValues = ["1, 0", "0, 1"]
    document.analysis.Group.append(displacement)
    force = type(
        "Force",
        (),
        {
            "Name": "Force",
            "Label": "Force",
            "TypeId": "Fem::ConstraintForce",
            "References": [(document.geometry, "Face1")],
            "DirectionVector": (0.0, 0.0, 0.0),
        },
    )()
    document.analysis.Group.append(force)
    result = operations.validate("Analysis")
    assert result["valid"] is False
    assert "constraint BadDisplacement has no references" in result["diagnostics"]
    assert "constraint BadDisplacement constrains no degrees of freedom" in result["diagnostics"]
    assert "constraint BadDisplacement amplitude is malformed" in result["diagnostics"]
    assert "load Force has a zero direction" in result["diagnostics"]
    assert "analysis may contain unconstrained rigid-body motion" in result["diagnostics"]


@pytest.mark.parametrize("scale", ["nan", "inf", "-inf", "1000000001"])
def test_validate_rejects_nonfinite_or_unbounded_amplitude_scale(scale: str) -> None:
    app, operations = _boundary_operations()
    amplitude = _NativeDisplacement("BadAmplitude")
    amplitude.EnableAmplitude = True
    amplitude.AmplitudeValues = ["0, {}".format(scale), "1, 1"]
    app.ActiveDocument.analysis.Group.append(amplitude)

    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert "constraint BadAmplitude amplitude is malformed" in diagnostics


def test_create_analysis_sets_frequency_native_controls_and_hz_limits() -> None:
    app = _AnalysisApp()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemForAnalysis)
    result = operations.create_analysis(
        "FrequencyAnalysis",
        "frequency",
        eigenmodes_count=4,
        frequency_low_hz=12.5,
        frequency_high_hz=250.0,
    )
    solver = _analysis_solver(app)
    assert result["analysis_type"] == "frequency"
    assert solver.AnalysisType == "frequency"
    assert solver.EigenmodesCount == 4
    assert solver.EigenmodeLow == "12.5 Hz"
    assert solver.EigenmodeHigh == "250 Hz"
    assert app.ActiveDocument.transaction_events[-1][0] == "commit"


def test_create_analysis_defaults_frequency_limits_to_zero_hz() -> None:
    app = _AnalysisApp()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemForAnalysis)
    operations.create_analysis("FrequencyAnalysis", "frequency", eigenmodes_count=1)
    solver = _analysis_solver(app)
    assert solver.EigenmodeLow == "0 Hz"
    assert solver.EigenmodeHigh == "0 Hz"


def test_create_analysis_sets_buckling_controls() -> None:
    app = _AnalysisApp()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemForAnalysis)
    operations.create_analysis(
        "BucklingAnalysis",
        "buckling",
        buckling_factors=8,
        buckling_accuracy=0.05,
    )
    solver = _analysis_solver(app)
    assert solver.AnalysisType == "buckling"
    assert solver.BucklingFactors == 8
    assert solver.BucklingAccuracy == 0.05


@pytest.mark.parametrize(
    "analysis_type, kwargs",
    [
        ("static", {"eigenmodes_count": 1}),
        ("frequency", {"eigenmodes_count": 1, "frequency_low_hz": 1.0}),
        ("frequency", {"eigenmodes_count": 1, "frequency_low_hz": 1.0, "frequency_high_hz": 1.0}),
        ("buckling", {"buckling_factors": 1}),
    ],
)
def test_create_analysis_rejects_invalid_mode_contract(analysis_type, kwargs) -> None:
    app = _AnalysisApp()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemForAnalysis)
    with pytest.raises(OperationError):
        operations.create_analysis("Analysis", analysis_type, **kwargs)


def test_create_analysis_rolls_back_when_required_native_property_is_missing() -> None:
    class _SolverWithoutBucklingAccuracy(_NativeSolverForAnalysis):
        _allowed = _NativeSolverForAnalysis._allowed

        def __init__(self, name: str):
            super().__init__(name)
            object.__delattr__(self, "BucklingAccuracy")

    app = _AnalysisApp(_SolverWithoutBucklingAccuracy)
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemForAnalysis)
    with pytest.raises(OperationError):
        operations.create_analysis(
            "BucklingAnalysis", "buckling", buckling_factors=2, buckling_accuracy=0.1
        )
    assert app.ActiveDocument.transaction_events[-1][0] == "abort"
    analysis = app.ActiveDocument.getObject("BucklingAnalysis")
    assert analysis is not None
    assert analysis.Group == []


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


def test_validate_centrifugal_rotation_axis_uses_native_edge_reference() -> None:
    app = _ConnectionApp()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithCentrifugal)
    load = _NativeCentrifugal("Centrifugal")
    load.References = [(app.ActiveDocument.geometry, "Solid1")]
    load.RotationAxis = [(app.ActiveDocument.geometry, "Edge1")]
    load.RotationFrequency = "50.0 Hz"
    app.ActiveDocument.analysis.Group.append(load)

    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert not any("rotation axis" in str(item).lower() for item in diagnostics)
    assert not any("zero direction" in str(item).lower() for item in diagnostics)


@pytest.mark.parametrize(
    "axis,expected",
    [
        ([("Geometry", "Edge999")], "rotation axis subelement is stale"),
        ([("Geometry", "Face1")], "rotation axis must be an Edge"),
    ],
)
def test_validate_centrifugal_rotation_axis_reports_stale_or_non_edge(axis, expected: str) -> None:
    app = _ConnectionApp()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithCentrifugal)
    load = _NativeCentrifugal("Centrifugal")
    load.References = []  # Empty means all solids for the global body load.
    load.RotationAxis = [(app.ActiveDocument.geometry, axis[0][1])]
    load.RotationFrequency = "50.0 Hz"
    app.ActiveDocument.analysis.Group.append(load)

    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert "load Centrifugal " + expected in diagnostics


def test_validate_tie_and_centrifugal_references_enforce_native_shape_kinds() -> None:
    app = _ConnectionApp()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithCentrifugal)
    tie = _NativeTie("Tie")
    tie.References = [(app.ActiveDocument.geometry, "Edge1")]
    app.ActiveDocument.analysis.Group.append(tie)
    load = _NativeCentrifugal("Centrifugal")
    load.References = [(app.ActiveDocument.geometry, "Face1")]
    load.RotationAxis = [(app.ActiveDocument.geometry, "Edge1")]
    load.RotationFrequency = "50.0 Hz"
    app.ActiveDocument.analysis.Group.append(load)

    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert "constraint Tie requires Face references" in diagnostics
    assert "constraint Centrifugal requires Solid references" in diagnostics


def test_validate_normalizes_native_property_link_sublist_references() -> None:
    app = _ConnectionApp()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithConnections)
    geometry = app.ActiveDocument.geometry
    single_pair = (geometry, ("Face1",))

    # FreeCAD 1.1 returns a list of pairs, but accepting one pair directly is
    # useful for native properties that expose a single link/sub-list value.
    assert FreeCADOperations._normalize_native_references(single_pair) == [
        (geometry, "Face1")
    ]
    assert FreeCADOperations._normalize_native_references([single_pair]) == [
        (geometry, "Face1")
    ]
    assert FreeCADOperations._normalize_native_references(
        [single_pair, (geometry, ("Face2",))]
    ) == [(geometry, "Face1"), (geometry, "Face2")]

    tie = _NativeTie("NativeLinkSubListTie")
    tie.References = [single_pair]
    assert operations._reference_diagnostics(tie) == []


@pytest.mark.parametrize(
    "subelements, expected",
    [
        (("Face999",), "constraint NativeLinkSubListTie reference 1 is stale"),
        (("Edge1",), "constraint NativeLinkSubListTie requires Face references"),
        (("Face1", None), "constraint NativeLinkSubListTie reference 2 is empty"),
    ],
)
def test_validate_native_property_link_sublist_preserves_reference_diagnostics(
    subelements: tuple[object, ...], expected: str
) -> None:
    app = _ConnectionApp()
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithConnections)
    tie = _NativeTie("NativeLinkSubListTie")
    tie.References = [(app.ActiveDocument.geometry, subelements)]

    diagnostics = operations._reference_diagnostics(tie)
    assert expected in diagnostics


def test_validate_buckling_with_centrifugal_load_still_requires_density() -> None:
    app = _ConnectionApp()
    app.ActiveDocument.analysis.Group[0].AnalysisType = "buckling"
    operations = FreeCADOperations(app=app, objects_fem=_ObjectsFemWithCentrifugal)
    load = _NativeCentrifugal("Centrifugal")
    load.References = []
    load.RotationAxis = [(app.ActiveDocument.geometry, "Edge1")]
    load.RotationFrequency = "50.0 Hz"
    app.ActiveDocument.analysis.Group.append(load)

    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert "body load requires material density" in diagnostics


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
