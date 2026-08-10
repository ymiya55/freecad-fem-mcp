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
        "rotxFree", "rotyFree", "rotzFree",
        "xRotation", "yRotation", "zRotation",
        "EnableAmplitude", "AmplitudeValues",
    }

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native displacement property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name, self.Label, self.TypeId = name, name, "Fem::ConstraintDisplacement"
        self.References = []
        self.xFree = self.yFree = self.zFree = True
        self.xDisplacement = self.yDisplacement = self.zDisplacement = None
        self.rotxFree = self.rotyFree = self.rotzFree = True
        self.xRotation = self.yRotation = self.zRotation = None
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
            "Edge2": _ShapeElement("Edge", "Part::GeomLine"),
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
    ExcludeBendingStiffness = False
    BeamReducedIntegration = False

    def getTypeIdOfProperty(self, name):
        return {"ExcludeBendingStiffness": "App::PropertyBool", "BeamReducedIntegration": "App::PropertyBool"}[name]


class _NativeConnectionSolverWithoutReduced:
    TypeId = "Fem::SolverCalculiX"
    AnalysisType = "static"
    ExcludeBendingStiffness = False


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


class _NativeCyclicTie(_NativeTie):
    _allowed = _NativeTie._allowed | {"Sectors", "ConnectedSectors"}

    def __init__(self, name: str):
        super().__init__(name)
        self.Sectors = 0
        self.ConnectedSectors = 1


class _NativePlaneRotation:
    _allowed = {"Name", "Label", "TypeId", "References"}

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native plane-rotation property: {}".format(name))
        object.__setattr__(self, name, value)

    def __init__(self, name: str):
        self.Name = self.Label = name
        self.TypeId = "Fem::ConstraintPlaneRotation"
        self.References = []


class _NativeContact:
    _allowed = {
        "Name", "Label", "TypeId", "References", "SurfaceBehavior", "Friction",
        "EnableThermalContact", "FrictionCoefficient", "Slope", "StickSlope", "Adjust",
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
        self.FrictionCoefficient = 0.0
        self.Slope = 0.0
        self.StickSlope = 0.0
        self.Adjust = 0.0


class _ConnectionAnalysis:
    TypeId = "Fem::FemAnalysis"

    def __init__(self, name: str = "Analysis", solver_factory=_NativeConnectionSolver):
        self.Name = self.Label = name
        self.Group = [solver_factory()]

    def addObject(self, obj):
        self.Group.append(obj)


class _ConnectionDocument:
    Name = "Doc"

    def __init__(self, solver_factory=_NativeConnectionSolver):
        self.analysis = _ConnectionAnalysis(solver_factory=solver_factory)
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
    def __init__(self, solver_factory=_NativeConnectionSolver):
        self.ActiveDocument = _ConnectionDocument(solver_factory=solver_factory)

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


class _ObjectsFemWithR4Connections(_ObjectsFemWithConnections):
    @staticmethod
    def makeConstraintTie(_doc, name):
        return _NativeCyclicTie(name)

    @staticmethod
    def makeConstraintPlaneRotation(_doc, name):
        return _NativePlaneRotation(name)


class _NativeElementGeometry:
    """Closed native-shaped geometry object for section/rotation mapping tests."""

    _property_types = {
        "References": "App::PropertyLinkSubListGlobal",
        "SectionType": "App::PropertyEnumeration",
        "RectWidth": "App::PropertyLength",
        "RectHeight": "App::PropertyLength",
        "CircDiameter": "App::PropertyLength",
        "PipeDiameter": "App::PropertyLength",
        "PipeThickness": "App::PropertyLength",
        "Axis1Length": "App::PropertyLength",
        "Axis2Length": "App::PropertyLength",
        "BoxHeight": "App::PropertyLength",
        "BoxWidth": "App::PropertyLength",
        "BoxT1": "App::PropertyLength",
        "BoxT2": "App::PropertyLength",
        "BoxT3": "App::PropertyLength",
        "BoxT4": "App::PropertyLength",
        "TrussArea": "App::PropertyArea",
        "Thickness": "App::PropertyLength",
        "Offset": "App::PropertyFloat",
        "Rotation": "App::PropertyAngle",
    }

    def __init__(self, name: str, semantic_type: str):
        object.__setattr__(self, "Name", name)
        object.__setattr__(self, "Label", name)
        object.__setattr__(self, "TypeId", "Fem::FeaturePython")
        object.__setattr__(self, "Proxy", type("Proxy", (), {"Type": semantic_type})())
        for prop in self._property_types:
            object.__setattr__(self, prop, [] if prop == "References" else None)

    def __setattr__(self, name, value):
        if name not in self._property_types and name not in {"Name", "Label", "TypeId", "Proxy"}:
            raise AssertionError("unexpected native element property: {}".format(name))
        object.__setattr__(self, name, value)

    def getTypeIdOfProperty(self, name):
        return self._property_types[name]


class _NativeConstraintTransform:
    _property_types = {
        "References": "App::PropertyLinkSubList",
        "TransformType": "App::PropertyEnumeration",
        "BasePoint": "App::PropertyVector",
        "Axis": "App::PropertyVector",
        "Rotation": "App::PropertyRotation",
    }

    def __init__(self, name: str):
        object.__setattr__(self, "Name", name)
        object.__setattr__(self, "Label", name)
        object.__setattr__(self, "TypeId", "Fem::ConstraintTransform")
        for prop in self._property_types:
            object.__setattr__(self, prop, [] if prop == "References" else None)

    def __setattr__(self, name, value):
        if name not in self._property_types and name not in {"Name", "Label", "TypeId"}:
            raise AssertionError("unexpected native transform property: {}".format(name))
        object.__setattr__(self, name, value)

    def getTypeIdOfProperty(self, name):
        return self._property_types[name]


class _NativeMaterial:
    _property_types = {
        "References": "App::PropertyLinkSubListGlobal",
        "Material": "App::PropertyMap",
    }

    def __init__(self, name: str):
        object.__setattr__(self, "Name", name)
        object.__setattr__(self, "Label", name)
        object.__setattr__(self, "TypeId", "App::MaterialObjectPython")
        object.__setattr__(self, "Category", "Solid")
        object.__setattr__(self, "References", [])
        object.__setattr__(self, "Material", {
            "Name": name,
            "YoungsModulus": "210000 MPa",
            "PoissonRatio": "0.30",
            "Density": "7850 kg/m^3",
        })

    def __setattr__(self, name, value):
        if name not in self._property_types and name not in {"Name", "Label", "TypeId", "Category"}:
            raise AssertionError("unexpected native material property: {}".format(name))
        object.__setattr__(self, name, value)

    def getTypeIdOfProperty(self, name):
        return self._property_types[name]


class _NativeGmshMesh:
    _allowed = {"Name", "Label", "TypeId", "Shape", "ElementDimension"}

    def __init__(self, name: str):
        object.__setattr__(self, "Name", name)
        object.__setattr__(self, "Label", name)
        object.__setattr__(self, "TypeId", "Fem::FemMeshGmsh")
        object.__setattr__(self, "Shape", None)
        object.__setattr__(self, "ElementDimension", "From Shape")

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AssertionError("unexpected native mesh property: {}".format(name))
        object.__setattr__(self, name, value)


def _register_geometry(doc, obj):
    doc.Objects.append(obj)
    doc._objects[obj.Name] = obj
    return obj


class _ObjectsFemWithGeometry(_ObjectsFemWithConnections):
    @staticmethod
    def makeMeshGmsh(doc, name="GmshMesh"):
        return _register_geometry(doc, _NativeGmshMesh(name))

    @staticmethod
    def makeElementGeometry1D(doc, name="ElementGeometry1D"):
        return _register_geometry(doc, _NativeElementGeometry(name, "Fem::ElementGeometry1D"))

    @staticmethod
    def makeElementGeometry2D(doc, name="ElementGeometry2D"):
        return _register_geometry(doc, _NativeElementGeometry(name, "Fem::ElementGeometry2D"))

    @staticmethod
    def makeElementRotation1D(doc, name="ElementRotation1D"):
        return _register_geometry(doc, _NativeElementGeometry(name, "Fem::ElementRotation1D"))

    @staticmethod
    def makeConstraintTransform(doc, name="ConstraintTransform"):
        return _register_geometry(doc, _NativeConstraintTransform(name))

    @staticmethod
    def makeMaterialSolid(doc, name="MaterialSolid"):
        return _register_geometry(doc, _NativeMaterial(name))


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


def _element_refs(*subelements):
    return [{"object": "Geometry", "sub_element": item} for item in subelements]


def _geometry_operations(objects_fem=_ObjectsFemWithGeometry, solver_factory=_NativeConnectionSolver):
    app = _ConnectionApp(solver_factory=solver_factory)
    return app, FreeCADOperations(app=app, objects_fem=objects_fem)


def test_element_geometry_beam_section_maps_native_enum_dimensions_and_edges() -> None:
    app, operations = _geometry_operations()
    solver = app.ActiveDocument.analysis.Group[0]
    # A first normal beam section must explicitly select full integration.
    solver.BeamReducedIntegration = True
    result = operations.assign_element_geometry(
        "Analysis",
        "beam_section",
        {
            "references": _element_refs("Edge1"),
            "section_type": "rectangular",
            "rect_width_m": 0.02,
            "rect_height_m": 0.03,
        },
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert result["kind"] == "beam_section"
    assert native.Proxy.Type == "Fem::ElementGeometry1D"
    assert native.SectionType == "Rectangular"
    assert native.RectWidth == "0.02 m"
    assert native.RectHeight == "0.03 m"
    assert native.References == [(app.ActiveDocument.geometry, "Edge1")]
    assert solver.BeamReducedIntegration is False

    # Additional normal sections preserve the solver-global setting rather
    # than silently changing a value established by the existing beam set.
    solver.BeamReducedIntegration = True
    operations.assign_element_geometry(
        "Analysis",
        "beam_section",
        {
            "references": _element_refs("Edge1"),
            "section_type": "circular",
            "circ_diameter_m": 0.02,
        },
    )
    assert solver.BeamReducedIntegration is True


def test_material_references_partition_regions_and_overlap_rolls_back() -> None:
    app, operations = _geometry_operations()
    first = operations.set_material(
        "Analysis",
        {
            "name": "MaterialEdge1",
            "targets": [{"object_name": "Geometry", "subelements": ["Edge1"]}],
        },
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert first["references"] == 1
    assert native.References == [(app.ActiveDocument.geometry, "Edge1")]
    operations.set_material(
        "Analysis",
        {
            "name": "MaterialEdge2",
            "references": [{"object": "Geometry", "sub_element": "Edge2"}],
        },
    )
    before = list(app.ActiveDocument.analysis.Group)
    with pytest.raises(OperationError, match="overlap"):
        operations.set_material(
            "Analysis",
            {
                "name": "MaterialOverlap",
                "references": [{"object": "Geometry", "sub_element": "Edge1"}],
            },
        )
    assert app.ActiveDocument.analysis.Group == before

    with pytest.raises(OperationError, match="additional materials"):
        operations.set_material("Analysis", {"name": "MaterialGlobal"})


def test_transform_constraint_maps_rectangular_and_cylindrical_native_properties() -> None:
    app, operations = _geometry_operations()
    operations.assign_element_geometry(
        "Analysis",
        "beam_section",
        {
            "references": _element_refs("Edge1"),
            "section_type": "rectangular",
            "rect_width_m": 0.01,
            "rect_height_m": 0.02,
        },
    )
    rectangular = operations.add_constraint(
        "Analysis",
        "transform",
        {
            "references": _element_refs("Edge1"),
            "transform_type": "rectangular",
            "rotation_rad": [0.0, 0.0, 0.5],
        },
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert rectangular["kind"] == "transform"
    assert native.TransformType == "Rectangular"
    assert native.BasePoint is None
    assert native.Rotation == (0.0, 0.0, 0.5)

    app, operations = _geometry_operations()
    operations.assign_element_geometry(
        "Analysis",
        "shell",
        {"references": [{"object": "Geometry", "sub_element": "Face1"}], "thickness_m": 0.001},
    )
    operations.add_constraint(
        "Analysis",
        "transform",
        {
            "references": [{"object": "Geometry", "sub_element": "Face1"}],
            "transform_type": "cylindrical",
            "base_point_m": [0.0, 0.0, 0.1],
            "axis_m": [0.0, 0.0, 1.0],
        },
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert native.TransformType == "Cylindrical"
    assert native.BasePoint == (0.0, 0.0, 100.0)
    assert native.Axis == (0.0, 0.0, 1000.0)


def test_transform_missing_factory_or_wrong_domain_aborts_transaction() -> None:
    app, operations = _geometry_operations(objects_fem=object())
    before = list(app.ActiveDocument.analysis.Group)
    with pytest.raises(OperationError, match="factory"):
        operations.add_constraint(
            "Analysis",
            "transform",
            {
                "references": _element_refs("Edge1"),
                "transform_type": "rectangular",
                "rotation_rad": [0.0, 0.0, 0.0],
            },
        )
    assert app.ActiveDocument.analysis.Group == before


def test_validate_reports_material_region_overlap_and_missing_coverage() -> None:
    app, operations = _geometry_operations()
    operations.assign_element_geometry(
        "Analysis",
        "beam_section",
        {
            "references": _element_refs("Edge1"),
            "section_type": "rectangular",
            "rect_width_m": 0.01,
            "rect_height_m": 0.02,
        },
    )
    operations.assign_element_geometry(
        "Analysis",
        "beam_section",
        {
            "references": _element_refs("Edge2"),
            "section_type": "circular",
            "circ_diameter_m": 0.02,
        },
    )
    operations.set_material(
        "Analysis",
        {"name": "MaterialEdge1", "targets": [{"object_name": "Geometry", "subelements": ["Edge1"]}]},
    )
    operations.set_material(
        "Analysis",
        {"name": "MaterialEdge2", "targets": [{"object_name": "Geometry", "subelements": ["Edge2"]}]},
    )
    mesh = type(
        "BeamMesh",
        (),
        {"Name": "BeamMesh", "Label": "BeamMesh", "TypeId": "Fem::FemMeshGmsh", "ElementDimension": "1D"},
    )()
    app.ActiveDocument.analysis.Group.append(mesh)
    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert not any("material coverage is missing" in str(item) for item in diagnostics)

    # A persisted stale reference must be surfaced before writer start.
    material = next(
        item for item in app.ActiveDocument.analysis.Group if item.TypeId == "App::MaterialObjectPython"
    )
    material.References = [(app.ActiveDocument.geometry, "Edge999")]
    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert any("material MaterialEdge1 reference 1 is stale" in str(item) for item in diagnostics)
    assert any("material coverage is missing" in str(item) for item in diagnostics)


def test_validate_reports_reopened_transform_shape_and_axis_contract() -> None:
    app, operations = _geometry_operations()
    operations.assign_element_geometry(
        "Analysis",
        "beam_section",
        {
            "references": _element_refs("Edge1"),
            "section_type": "rectangular",
            "rect_width_m": 0.01,
            "rect_height_m": 0.02,
        },
    )
    operations.add_constraint(
        "Analysis",
        "transform",
        {
            "references": _element_refs("Edge1"),
            "transform_type": "cylindrical",
            "base_point_m": [0.0, 0.0, 0.0],
            "axis_m": [0.0, 0.0, 1.0],
        },
    )
    transform = app.ActiveDocument.analysis.Group[-1]
    transform.Axis = (0.0, 0.0, 0.0)
    transform.References = [(app.ActiveDocument.geometry, "Face1")]
    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert any("transform" in str(item).lower() and "axis" in str(item).lower() for item in diagnostics)
    assert any("transform" in str(item).lower() and "analysis geometry" in str(item).lower() for item in diagnostics)


def test_element_geometry_shell_and_rotation_map_native_face_edge_properties() -> None:
    app, operations = _geometry_operations()
    shell = operations.assign_element_geometry(
        "Analysis",
        "shell",
        {"references": _element_refs("Face1"), "thickness_m": 0.002, "offset": -0.25},
    )
    shell_native = app.ActiveDocument.analysis.Group[-1]
    assert shell["kind"] == "shell"
    assert shell_native.Proxy.Type == "Fem::ElementGeometry2D"
    assert shell_native.Thickness == "0.002 m"
    assert shell_native.Offset == -0.25

    app, operations = _geometry_operations()
    rotation = operations.assign_element_geometry(
        "Analysis",
        "beam_rotation",
        {"references": _element_refs("Edge1"), "rotation_rad": 0.5},
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert rotation["kind"] == "beam_rotation"
    assert native.Proxy.Type == "Fem::ElementRotation1D"
    assert native.Rotation == "0.5 rad"
    assert native.References == [(app.ActiveDocument.geometry, "Edge1")]


def test_element_geometry_membrane_maps_solver_formulation_and_rejects_mixing() -> None:
    app, operations = _geometry_operations()
    membrane = operations.assign_element_geometry(
        "Analysis",
        "shell",
        {
            "references": _element_refs("Face1"),
            "formulation": "membrane",
            "thickness_m": 0.001,
        },
    )
    assert membrane["formulation"] == "membrane"
    solver = app.ActiveDocument.analysis.Group[0]
    assert solver.ExcludeBendingStiffness is True

    operations.assign_element_geometry(
        "Analysis",
        "shell",
        {
            "references": _element_refs("Face2"),
            "formulation": "membrane",
            "thickness_m": 0.001,
        },
    )
    before = list(app.ActiveDocument.analysis.Group)
    with pytest.raises(OperationError):
        operations.assign_element_geometry(
            "Analysis",
            "shell",
            {"references": _element_refs("Face1"), "formulation": "shell", "thickness_m": 0.001},
        )
    assert app.ActiveDocument.analysis.Group == before
    with pytest.raises(OperationError):
        operations.assign_element_geometry(
            "Analysis",
            "beam_section",
            {
                "references": _element_refs("Edge1"),
                "section_type": "rectangular",
                "rect_width_m": 0.01,
                "rect_height_m": 0.02,
            },
        )


@pytest.mark.parametrize(
    "section_type,values,expected",
    [
        ("circular", {"circ_diameter_m": 0.02}, "Circular"),
        ("pipe", {"pipe_diameter_m": 0.03, "pipe_thickness_m": 0.002}, "Pipe"),
        ("elliptical", {"axis1_length_m": 0.03, "axis2_length_m": 0.02}, "Elliptical"),
        ("box", {"box_width_m": 0.03, "box_height_m": 0.04, "box_t1_m": 0.002, "box_t2_m": 0.002, "box_t3_m": 0.002, "box_t4_m": 0.002}, "Box"),
        ("truss", {"truss_area_m2": 0.0002}, "Rectangular"),
    ],
)
def test_element_geometry_beam_section_enum_contract(section_type, values, expected) -> None:
    app, operations = _geometry_operations()
    operations.assign_element_geometry(
        "Analysis", "beam_section", {"references": _element_refs("Edge1"), "section_type": section_type, **values}
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert native.SectionType == expected
    if section_type == "pipe":
        assert app.ActiveDocument.analysis.Group[0].BeamReducedIntegration is True
    if section_type == "truss":
        assert native.TrussArea == "0.0002 m^2"
        assert app.ActiveDocument.analysis.Group[0].ExcludeBendingStiffness is True


@pytest.mark.parametrize(
    "params",
    [
        {"references": _element_refs("Face1"), "thickness_m": 0.001, "offset": 2.0},
        {"references": _element_refs("Edge1"), "section_type": "pipe", "pipe_diameter_m": 0.01, "pipe_thickness_m": 0.005},
        {"references": _element_refs("Edge1"), "section_type": "box", "box_width_m": 0.01, "box_height_m": 0.01, "box_t1_m": 0.006, "box_t2_m": 0.001, "box_t3_m": 0.005, "box_t4_m": 0.001},
        {"references": _element_refs("Face1"), "thickness_m": 0.001, "section_type": "circular"},
        {"references": _element_refs("Edge1", "Edge1"), "section_type": "rectangular", "rect_width_m": 0.01, "rect_height_m": 0.02},
        {"references": _element_refs("Face1"), "section_type": "rectangular", "rect_width_m": 0.01, "rect_height_m": 0.02},
    ],
)
def test_element_geometry_rejects_wrong_duplicate_or_inconsistent_contract(params) -> None:
    app, operations = _geometry_operations()
    before = list(app.ActiveDocument.analysis.Group)
    kind = "shell" if "thickness_m" in params else "beam_section"
    with pytest.raises(OperationError):
        operations.assign_element_geometry("Analysis", kind, params)
    assert app.ActiveDocument.analysis.Group == before


def test_truss_normal_beam_does_not_silently_clear_solver_exclusion_and_shell_conflicts() -> None:
    app, operations = _geometry_operations()
    operations.assign_element_geometry(
        "Analysis", "beam_section", {"references": _element_refs("Edge1"), "section_type": "truss", "truss_area_m2": 0.0002}
    )
    operations.assign_element_geometry(
        "Analysis", "beam_section", {"references": _element_refs("Edge1"), "section_type": "truss", "truss_area_m2": 0.0003}
    )
    assert app.ActiveDocument.analysis.Group[0].ExcludeBendingStiffness is True
    before = list(app.ActiveDocument.analysis.Group)
    with pytest.raises(OperationError):
        operations.assign_element_geometry(
            "Analysis", "beam_section", {"references": _element_refs("Edge1"), "section_type": "rectangular", "rect_width_m": 0.01, "rect_height_m": 0.02}
        )
    assert app.ActiveDocument.analysis.Group == before
    with pytest.raises(OperationError):
        operations.assign_element_geometry(
            "Analysis", "shell", {"references": _element_refs("Face1"), "thickness_m": 0.001}
        )


def test_element_geometry_missing_factory_or_property_aborts_transaction() -> None:
    app, operations = _geometry_operations(objects_fem=object())
    with pytest.raises(OperationError):
        operations.assign_element_geometry(
            "Analysis", "shell", {"references": _element_refs("Face1"), "thickness_m": 0.001}
        )
    assert app.ActiveDocument.transaction_events[-1][0] == "abort"
    assert len(app.ActiveDocument.analysis.Group) == 1

    # The first normal beam section also requires the native reduced-
    # integration property; a missing property must leave no geometry behind.
    app, operations = _geometry_operations(solver_factory=_NativeConnectionSolverWithoutReduced)
    with pytest.raises(OperationError):
        operations.assign_element_geometry(
            "Analysis",
            "beam_section",
            {
                "references": _element_refs("Edge1"),
                "section_type": "rectangular",
                "rect_width_m": 0.01,
                "rect_height_m": 0.02,
            },
        )
    assert app.ActiveDocument.transaction_events[-1][0] == "abort"
    assert len(app.ActiveDocument.analysis.Group) == 1

    app, operations = _geometry_operations(solver_factory=_NativeConnectionSolverWithoutReduced)
    with pytest.raises(OperationError):
        operations.assign_element_geometry(
            "Analysis",
            "beam_section",
            {
                "references": _element_refs("Edge1"),
                "section_type": "pipe",
                "pipe_diameter_m": 0.03,
                "pipe_thickness_m": 0.002,
            },
        )
    assert app.ActiveDocument.transaction_events[-1][0] == "abort"
    assert len(app.ActiveDocument.analysis.Group) == 1

    class _MissingReferences(_ObjectsFemWithGeometry):
        @staticmethod
        def makeElementGeometry2D(doc, name="ElementGeometry2D"):
            obj = _register_geometry(doc, _NativeElementGeometry(name, "Fem::ElementGeometry2D"))
            object.__delattr__(obj, "References")
            return obj

    app, operations = _geometry_operations(objects_fem=_MissingReferences)
    with pytest.raises(OperationError):
        operations.assign_element_geometry(
            "Analysis", "shell", {"references": _element_refs("Face1"), "thickness_m": 0.001}
        )
    assert app.ActiveDocument.transaction_events[-1][0] == "abort"


def test_beam_displacement_maps_translation_and_rotation_native_dofs() -> None:
    class _BeamBoundaryObjectsFem(_ObjectsFemWithGeometry):
        @staticmethod
        def makeConstraintDisplacement(_doc, name):
            return _NativeDisplacement(name)

    app, operations = _geometry_operations(objects_fem=_BeamBoundaryObjectsFem)
    operations.assign_element_geometry(
        "Analysis",
        "beam_section",
        {
            "references": _element_refs("Edge1"),
            "section_type": "rectangular",
            "rect_width_m": 0.01,
            "rect_height_m": 0.02,
        },
    )
    operations.assign_element_geometry(
        "Analysis",
        "beam_rotation",
        {"references": _element_refs("Edge1"), "rotation_rad": 0.0},
    )
    result = operations.add_constraint(
        "Analysis",
        "displacement",
        {
            "references": _element_refs("Edge1"),
            "x": None,
            "y": 0.001,
            "z": None,
            "xFree": True,
            "yFree": False,
            "zFree": True,
            "rotx": 0.25,
            "roty": None,
            "rotz": None,
            "rotxFree": False,
            "rotyFree": True,
            "rotzFree": True,
        },
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert result["kind"] == "displacement"
    assert native.yDisplacement == "0.001 m"
    assert native.xRotation == "0.25 rad"
    assert (native.xFree, native.yFree, native.zFree) == (True, False, True)
    assert (native.rotxFree, native.rotyFree, native.rotzFree) == (False, True, True)


def test_solid_displacement_rejects_rotation_and_rolls_back() -> None:
    app, operations = _boundary_operations()
    before = list(app.ActiveDocument.analysis.Group)
    with pytest.raises(OperationError, match="beam or shell"):
        operations.add_constraint(
            "Analysis",
            "displacement",
            {
                "references": _connection_refs("Face1"),
                "x": None,
                "y": None,
                "z": None,
                "xFree": True,
                "yFree": True,
                "zFree": True,
                "rotx": 0.1,
                "rotxFree": False,
            },
        )
    assert app.ActiveDocument.analysis.Group == before


def test_create_mesh_element_dimension_maps_native_enum_and_missing_property_fails_closed() -> None:
    app, operations = _geometry_operations()
    result = operations.create_mesh("Analysis", element_dimension="2d", shape="Geometry")
    native = app.ActiveDocument.analysis.Group[-1]
    assert result["name"] == native.Name
    assert native.ElementDimension == "2D"

    class _MissingDimension(_ObjectsFemWithGeometry):
        @staticmethod
        def makeMeshGmsh(doc, name="GmshMesh"):
            obj = _register_geometry(doc, _NativeGmshMesh(name))
            object.__delattr__(obj, "ElementDimension")
            return obj

    app, operations = _geometry_operations(objects_fem=_MissingDimension)
    with pytest.raises(OperationError):
        operations.create_mesh("Analysis", element_dimension="1d", shape="Geometry")
    assert app.ActiveDocument.transaction_events[-1][0] == "abort"


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


def test_contact_connection_maps_linear_friction_and_si_stiffness() -> None:
    app, operations = _connection_operations()
    result = operations.add_connection(
        "Analysis",
        "contact",
        {
            "references": _connection_refs("Face2", "Face1"),
            "surface_behavior": "linear",
            "normal_stiffness_pa_per_m": 1.0e9,
            "friction": True,
            "friction_coefficient": 0.25,
            "stick_stiffness_pa_per_m": 3.0e9,
            "adjust_m": 0.004,
        },
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert result["kind"] == "contact"
    assert native.SurfaceBehavior == "Linear"
    assert native.Friction is True
    assert native.FrictionCoefficient == 0.25
    assert native.Slope == "1000000000.0 Pa/m"
    assert native.StickSlope == "3000000000.0 Pa/m"
    assert native.Adjust == "0.004 m"


@pytest.mark.parametrize(
    "params",
    [
        {"surface_behavior": "linear"},
        {"surface_behavior": "tied"},
        {"surface_behavior": "hard", "normal_stiffness_pa_per_m": 1.0},
        {"surface_behavior": "linear", "normal_stiffness_pa_per_m": 0.0},
        {
            "surface_behavior": "hard",
            "friction": True,
            "friction_coefficient": 0.2,
        },
        {"surface_behavior": "hard", "friction_coefficient": 0.2},
        {"surface_behavior": "hard", "adjust_m": float("nan")},
    ],
)
def test_contact_connection_rejects_invalid_native_field_combinations(params) -> None:
    _app, operations = _connection_operations()
    with pytest.raises(OperationError):
        operations.add_connection(
            "Analysis",
            "contact",
            {"references": _connection_refs("Face1", "Face2"), **params},
        )


def test_tie_connection_rejects_explicit_friction_field_even_false() -> None:
    _app, operations = _connection_operations()
    with pytest.raises(OperationError):
        operations.add_connection(
            "Analysis",
            "tie",
            {
                "references": _connection_refs("Face1", "Face2"),
                "tolerance_m": 0.0,
                "adjust": False,
                "friction": False,
            },
        )


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


def test_cyclic_symmetry_maps_native_tie_fields_and_preserves_face_order() -> None:
    app, operations = _connection_operations(_ObjectsFemWithR4Connections)
    result = operations.add_connection(
        "Analysis",
        "cyclic_symmetry",
        {
            "references": _connection_refs("Face2", "Face1"),
            "tolerance_m": 0.002,
            "adjust": False,
            "sectors": 4,
            "connected_sectors": 2,
        },
    )
    native = app.ActiveDocument.analysis.Group[-1]
    assert result["kind"] == "cyclic_symmetry"
    assert native.TypeId == "Fem::ConstraintTie"
    assert native.References == [
        (app.ActiveDocument.geometry, "Face2"),
        (app.ActiveDocument.geometry, "Face1"),
    ]
    assert native.Tolerance == 2.0
    assert native.Adjust is False
    assert native.CyclicSymmetry is True
    assert native.Sectors == 4
    assert native.ConnectedSectors == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"references": _connection_refs("Face1", "Edge1")},
        {"references": _connection_refs("Face1", "Face1")},
        {"sectors": 1, "connected_sectors": 1},
        {"sectors": 4, "connected_sectors": 0},
        {"sectors": 4, "connected_sectors": 4},
        {"sectors": 1_000_001, "connected_sectors": 1},
    ],
)
def test_cyclic_symmetry_rejects_invalid_faces_or_sector_bounds(bad) -> None:
    app, operations = _connection_operations(_ObjectsFemWithR4Connections)
    params = {
        "references": _connection_refs("Face1", "Face2"),
        "tolerance_m": 0.0,
        "adjust": True,
        "sectors": 4,
        "connected_sectors": 1,
    }
    params.update(bad)
    before = list(app.ActiveDocument.analysis.Group)
    with pytest.raises(OperationError):
        operations.add_connection("Analysis", "cyclic_symmetry", params)
    assert app.ActiveDocument.analysis.Group == before


def test_cyclic_symmetry_is_static_only_and_rolls_back() -> None:
    app, operations = _connection_operations(_ObjectsFemWithR4Connections)
    app.ActiveDocument.analysis.Group[0].AnalysisType = "frequency"
    with pytest.raises(OperationError):
        operations.add_connection(
            "Analysis",
            "cyclic_symmetry",
            {
                "references": _connection_refs("Face1", "Face2"),
                "tolerance_m": 0.0,
                "adjust": True,
                "sectors": 2,
                "connected_sectors": 1,
            },
        )
    assert len(app.ActiveDocument.analysis.Group) == 1


def test_plane_rotation_accepts_native_mesh_reference_shapes() -> None:
    app, operations = _connection_operations(_ObjectsFemWithR4Connections)
    for sub_element in ("Face1", "Edge1", "Vertex1", "Solid1", ""):
        result = operations.add_constraint(
            "Analysis",
            "plane_rotation",
            {"references": [{"object": "Geometry", "sub_element": sub_element}]},
        )
        native = app.ActiveDocument.analysis.Group[-1]
        assert result["kind"] == "plane_rotation"
        assert native.TypeId == "Fem::ConstraintPlaneRotation"
        assert native.References == [(app.ActiveDocument.geometry, sub_element)]


@pytest.mark.parametrize(
    "references",
    [
        [],
        [{"object": "Geometry", "sub_element": "Face999"}],
        [{"object": "Geometry", "sub_element": "Wire1"}],
    ],
)
def test_plane_rotation_rejects_empty_or_stale_native_references(references) -> None:
    app, operations = _connection_operations(_ObjectsFemWithR4Connections)
    before = list(app.ActiveDocument.analysis.Group)
    with pytest.raises(OperationError):
        operations.add_constraint("Analysis", "plane_rotation", {"references": references})
    assert app.ActiveDocument.analysis.Group == before


def test_r4_operations_reject_unknown_native_escape_fields() -> None:
    _app, operations = _connection_operations(_ObjectsFemWithR4Connections)
    with pytest.raises(OperationError):
        operations.add_constraint(
            "Analysis",
            "plane_rotation",
            {
                "references": [{"object": "Geometry", "sub_element": "Face1"}],
                "Normals": [(0.0, 0.0, 1.0)],
            },
        )
    with pytest.raises(OperationError):
        operations.add_connection(
            "Analysis",
            "cyclic_symmetry",
            {
                "references": _connection_refs("Face1", "Face2"),
                "tolerance_m": 0.0,
                "adjust": True,
                "sectors": 2,
                "connected_sectors": 1,
                "symmetry_axis": {},
            },
        )

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


def test_validate_preserves_existing_3d_solid_requirements() -> None:
    app, operations = _connection_operations()
    analysis = app.ActiveDocument.analysis
    analysis.Group.extend(
        [
            type(
                "MaterialSolid",
                (),
                {"Name": "MaterialSolid", "Label": "MaterialSolid", "TypeId": "App::MaterialObjectPython"},
            )(),
            type(
                "SolidMesh",
                (),
                {"Name": "SolidMesh", "Label": "SolidMesh", "TypeId": "Fem::FemMeshGmsh"},
            )(),
        ]
    )
    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert not any("2d mesh" in str(item).lower() for item in diagnostics)
    assert not any("elementgeometry2d" in str(item).lower() for item in diagnostics)


def test_validate_beam_mode_checks_1d_mesh_section_material_and_solver() -> None:
    app, operations = _geometry_operations()
    operations.assign_element_geometry(
        "Analysis",
        "beam_section",
        {
            "references": _element_refs("Edge1"),
            "section_type": "rectangular",
            "rect_width_m": 0.01,
            "rect_height_m": 0.02,
        },
    )
    operations.assign_element_geometry(
        "Analysis",
        "beam_rotation",
        {"references": _element_refs("Edge1"), "rotation_rad": 0.0},
    )
    analysis = app.ActiveDocument.analysis
    analysis.Group.extend(
        [
            type("MaterialBeam", (), {"Name": "MaterialBeam", "Label": "MaterialBeam", "TypeId": "App::MaterialObjectPython"})(),
            type("BeamMesh", (), {"Name": "BeamMesh", "Label": "BeamMesh", "TypeId": "Fem::FemMeshGmsh", "ElementDimension": "1D"})(),
        ]
    )
    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert not any("1d mesh" in str(item).lower() for item in diagnostics)
    assert not any("elementgeometry1d beam section" in str(item).lower() for item in diagnostics)
    assert not any("invalid sectiontype" in str(item).lower() for item in diagnostics)

    analysis.Group[-1].ElementDimension = "3D"
    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert "analysis requires a 1D mesh (ElementDimension=1D)" in diagnostics


def test_validate_rejects_membrane_pressure_before_solver_start() -> None:
    app, operations = _connection_operations()
    analysis = app.ActiveDocument.analysis
    solver = analysis.Group[0]
    solver.ExcludeBendingStiffness = True
    analysis.Group.extend(
        [
            type(
                "MaterialShell",
                (),
                {"Name": "MaterialShell", "Label": "MaterialShell", "TypeId": "App::MaterialObjectPython"},
            )(),
            type(
                "ShellMesh",
                (),
                {
                    "Name": "ShellMesh",
                    "Label": "ShellMesh",
                    "TypeId": "Fem::FemMeshGmsh",
                    "ElementDimension": "2D",
                },
            )(),
            type(
                "ShellGeometry",
                (),
                {
                    "Name": "ShellGeometry",
                    "Label": "ShellGeometry",
                    "TypeId": "Fem::ElementGeometry2D",
                    "References": [(app.ActiveDocument.geometry, "Face1")],
                    "Thickness": "0.001 m",
                    "Offset": 0.0,
                },
            )(),
            type(
                "Pressure",
                (),
                {
                    "Name": "Pressure",
                    "Label": "Pressure",
                    "TypeId": "Fem::ConstraintPressure",
                    "References": [(app.ActiveDocument.geometry, "Face1")],
                    "Pressure": "1 Pa",
                },
            )(),
        ]
    )
    diagnostics = operations.validate("Analysis")["diagnostics"]
    assert "membrane formulation does not support ConstraintPressure" in diagnostics


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
