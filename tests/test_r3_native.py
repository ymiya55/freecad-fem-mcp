"""R3 native nonlinear/static single-step contract coverage."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[1] / "addon"))

from FreeCADFEMMCP.jobs import QProcessJobRegistry  # noqa: E402
from FreeCADFEMMCP.operations import FreeCADOperations, OperationError  # noqa: E402
from FreeCADFEMMCP.service import FEMService, ServiceError  # noqa: E402
from freecad_fem_mcp.models import AssignMaterialRequest, CreateAnalysisRequest  # noqa: E402


class _Solver:
    TypeId = "Fem::SolverCalculiX"

    def __init__(self, name: str = "CalculiX") -> None:
        self.Name = self.Label = name
        self.AnalysisType = "static"
        self.GeometricalNonlinearity = "linear"
        self.MaterialNonlinearity = "linear"
        self.AutomaticIncrementation = True
        self.IncrementsMaximum = 2000
        self.TimeInitialIncrement = "1 s"
        self.TimeMinimumIncrement = "1e-5 s"
        self.TimeMaximumIncrement = "1 s"
        self.TimePeriod = "1 s"


class _Analysis:
    TypeId = "Fem::FemAnalysis"

    def __init__(self) -> None:
        self.Name = self.Label = "Analysis"
        self.Group = []

    def addObject(self, obj):
        self.Group.append(obj)


class _Document:
    Name = "Doc"

    def __init__(self) -> None:
        self.analysis = _Analysis()
        self.Objects = [self.analysis]
        self._objects = {"Analysis": self.analysis}

    def getObject(self, name):
        return self._objects.get(name)

    def openTransaction(self, _label):
        pass

    def commitTransaction(self):
        pass

    def abortTransaction(self):
        pass

    def addObject(self, type_id, name):
        if type_id == "Fem::FemAnalysis":
            obj = _Analysis()
            obj.Name = obj.Label = name
            self.Objects.append(obj)
            self._objects[name] = obj
            return obj
        if type_id == "Fem::SolverCalculiX":
            obj = _Solver(name)
            self.Objects.append(obj)
            self._objects[name] = obj
            return obj
        obj = type("Native", (), {})()
        obj.Name = obj.Label = name
        obj.TypeId = type_id
        if type_id == "App::MaterialObjectPython":
            obj.Material = {}
        self.Objects.append(obj)
        self._objects[name] = obj
        return obj


class _App:
    def __init__(self) -> None:
        self.ActiveDocument = _Document()

    @staticmethod
    def Version():
        return ("1", "1", "3")


class _ObjectsFem:
    @staticmethod
    def makeMaterialSolid(doc, name):
        return doc.addObject("App::MaterialObjectPython", name)

    @staticmethod
    def makeMaterialMechanicalNonlinear(doc, base, name):
        obj = doc.addObject("Fem::FeaturePython", name)
        obj.LinearBaseMaterial = base
        obj.MaterialModelNonlinearity = "isotropic hardening"
        obj.YieldPoints = []
        return obj


def _operations() -> tuple[_App, FreeCADOperations]:
    app = _App()
    # create_analysis owns creation of the analysis container in this fake.
    app.ActiveDocument.Objects = []
    app.ActiveDocument._objects = {}
    return app, FreeCADOperations(app=app, objects_fem=_ObjectsFem)


def test_models_accept_bounded_static_r3_and_reject_nonmonotonic_points() -> None:
    request = CreateAnalysisRequest(
        geometrical_nonlinearity="nonlinear",
        material_nonlinearity="nonlinear",
        automatic_incrementation=False,
        time_initial_increment_s=0.1,
        time_minimum_increment_s=0.01,
        time_maximum_increment_s=0.2,
        time_period_s=1.0,
        increments_maximum=100,
    )
    assert request.time_period_s == 1.0
    material = AssignMaterialRequest(
        analysis_id="Analysis",
        hardening_model="kinematic",
        yield_points=[
            {"stress_pa": 275e6, "plastic_strain": 0.0},
            {"stress_pa": 490e6, "plastic_strain": 0.2},
        ],
    )
    assert material.yield_points is not None
    with pytest.raises(ValidationError):
        AssignMaterialRequest(
            analysis_id="Analysis",
            hardening_model="isotropic",
            yield_points=[
                {"stress_pa": 275e6, "plastic_strain": 0.1},
                {"stress_pa": 250e6, "plastic_strain": 0.0},
            ],
        )


def test_models_reject_r3_controls_for_modal_modes_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(
            analysis_type="frequency",
            eigenmodes_count=1,
            geometrical_nonlinearity="nonlinear",
        )
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(unknown_native_property=True)


def test_time_increment_controls_require_a_complete_single_step_tuple() -> None:
    with pytest.raises(ValidationError):
        CreateAnalysisRequest(time_period_s=1.0)
    with pytest.raises(ServiceError):
        FEMService._validate_analysis_options(
            {"analysis_type": "static", "time_period_s": 1.0}
        )
    with pytest.raises(OperationError):
        FreeCADOperations._analysis_options("static", time_period_s=1.0)


def test_operations_map_native_solver_controls_and_nonlinear_material() -> None:
    app, operations = _operations()
    result = operations.create_analysis(
        "Analysis",
        geometrical_nonlinearity="nonlinear",
        material_nonlinearity="nonlinear",
        automatic_incrementation=False,
        time_initial_increment_s=0.1,
        time_minimum_increment_s=0.01,
        time_maximum_increment_s=0.2,
        time_period_s=1.0,
        increments_maximum=50,
    )
    assert result["analysis_type"] == "static"
    nonlinear = operations.set_material(
        "Analysis",
        {
            "name": "MaterialSolid",
            "hardening_model": "isotropic",
            "yield_points": [
                {"stress_pa": 275e6, "plastic_strain": 0.0},
                {"stress_pa": 490e6, "plastic_strain": 0.2},
            ],
        },
    )
    app.ActiveDocument.analysis = app.ActiveDocument.getObject("Analysis")
    solver = app.ActiveDocument.analysis.Group[0]
    assert solver.GeometricalNonlinearity == "nonlinear"
    assert solver.AutomaticIncrementation is False
    assert solver.IncrementsMaximum == 50
    assert nonlinear["yield_points"] == ["275, 0", "490, 0.2"]


def test_service_double_validation_rejects_native_enum_and_unbounded_point() -> None:
    with pytest.raises(ServiceError):
        FEMService._validate_nonlinear_material(
            {"hardening_model": "isotropic hardening", "yield_points": []}
        )
    with pytest.raises(ServiceError):
        FEMService._validate_nonlinear_material(
            {
                "hardening_model": "isotropic",
                "yield_points": [
                    {"stress_pa": 1e16, "plastic_strain": 0.0},
                ],
            }
        )


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class _Process:
    def __init__(self):
        self.readyReadStandardOutput = _Signal()
        self.readyReadStandardError = _Signal()
        self.finished = _Signal()
        self.stdout = b""
        self.stderr = b""

    def readAllStandardOutput(self):
        value, self.stdout = self.stdout, b""
        return value

    def readAllStandardError(self):
        value, self.stderr = self.stderr, b""
        return value

    def exitCode(self):
        return 0


class _Tool:
    def __init__(self, process):
        self.process = process

    def run(self, blocking):
        assert blocking is False
        self.process.stdout = b"nonlinear solution converged; final increment 12\n"
        self.process.readyReadStandardOutput.emit()
        self.process.finished.emit(0, 0)


def test_jobs_emit_bounded_native_convergence_summary() -> None:
    process = _Process()
    registry = QProcessJobRegistry(
        calculix_factory=lambda _obj: _Tool(process),
    )
    result = registry.start_calculix(object())
    assert result["convergence"] == {
        "status": "converged",
        "source": "native_output",
        "final_increment": 12,
    }
