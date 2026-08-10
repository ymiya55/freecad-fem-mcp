"""FreeCAD 1.1.3 native R7.4 material/transform audit.

This executable probe only inspects native ``ObjectsFem`` factories and
CalculiX writer inputs.  It does not run a solver or inject an INP deck.
"""

from __future__ import annotations

import io
import json
from typing import Any


def _props(obj: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in getattr(obj, "PropertiesList", []):
        try:
            result[name] = obj.getTypeIdOfProperty(name)
        except Exception:
            result[name] = "<unavailable>"
    return result


def _factory_names(objects_fem: Any, token: str) -> list[str]:
    return sorted(name for name in dir(objects_fem) if token.lower() in name.lower())


def run() -> None:
    try:
        import FreeCAD as app  # type: ignore
        import ObjectsFem  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this probe with FreeCADCmd 1.1.3") from exc
    if getattr(app, "_R7NativeMaterialTransformAuditRunning", False):
        return
    app._R7NativeMaterialTransformAuditRunning = True
    doc = app.newDocument("R7MaterialTransformAudit")
    try:
        factory_results: dict[str, Any] = {
            "material_factories": _factory_names(ObjectsFem, "material"),
            "transform_factories": _factory_names(ObjectsFem, "transform"),
        }
        for factory_name in ("makeMaterialSolid", "makeConstraintTransform"):
            factory = getattr(ObjectsFem, factory_name, None)
            if not callable(factory):
                factory_results[factory_name] = {"available": False}
                continue
            try:
                obj = factory(doc, factory_name.removeprefix("make"))
            except Exception as exc:
                factory_results[factory_name] = {
                    "available": True,
                    "created": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                continue
            factory_results[factory_name] = {
                "available": True,
                "created": True,
                "type_id": getattr(obj, "TypeId", None),
                "proxy_type": getattr(getattr(obj, "Proxy", None), "Type", None),
                "proxy_module": type(getattr(obj, "Proxy", None)).__module__,
                "properties": _props(obj),
            }
            if factory_name == "makeConstraintTransform":
                try:
                    factory_results[factory_name]["transform_type_enums"] = obj.getEnumerationsOfProperty("TransformType")
                    factory_results[factory_name]["transform_type_default"] = obj.TransformType
                    factory_results[factory_name]["scale_value"] = obj.Scale
                except Exception as exc:
                    factory_results[factory_name]["enum_error_type"] = type(exc).__name__
        import femsolver.calculix as calculix  # type: ignore
        writer_modules = {}
        for module_name in (
            "write_materials",
            "write_constraints",
            "write_femelement_geometry",
            "writer",
        ):
            try:
                module = __import__(
                    "femsolver.calculix." + module_name,
                    fromlist=[module_name],
                )
                writer_modules[module_name] = sorted(
                    name for name in dir(module) if "transform" in name.lower() or "material" in name.lower()
                )
            except Exception as exc:
                writer_modules[module_name] = {"error_type": type(exc).__name__}
        writer_modules["calculix"] = sorted(
            name for name in dir(calculix) if "transform" in name.lower() or "material" in name.lower()
        )
        import inspect
        writer_api = {}
        for name in ("write_constraint_transform", "write_femelement_material"):
            function = getattr(calculix, name, None)
            writer_api[name] = {"type": type(function).__name__}
            if function is not None:
                writer_api[name]["members"] = sorted(
                    member for member in dir(function)
                    if member.startswith("write") or member.startswith("con_")
                )
                for member in writer_api[name]["members"]:
                    candidate = getattr(function, member, None)
                    if callable(candidate):
                        writer_api[name][member] = str(inspect.signature(candidate))
        transform_writer = getattr(calculix, "write_constraint_transform")
        transform_outputs: dict[str, str] = {}
        transform_obj = doc.getObject("ConstraintTransform")
        if transform_obj is not None:
            transform_obj.TransformType = "Rectangular"
            transform_obj.Rotation = app.Rotation(app.Vector(0, 0, 1), Radian=0.5)
            output = io.StringIO()
            transform_writer.write_meshdata_constraint(output, {"Nodes": [11, 12]}, transform_obj, None)
            transform_writer.write_constraint(output, {"Nodes": [11, 12]}, transform_obj, None)
            transform_outputs["rectangular"] = output.getvalue()
            transform_obj.TransformType = "Cylindrical"
            transform_obj.BasePoint = app.Vector(100, 200, 300)
            transform_obj.Axis = app.Vector(0, 0, 1000)
            output = io.StringIO()
            transform_writer.write_meshdata_constraint(output, {"Nodes": [21, 22]}, transform_obj, None)
            transform_writer.write_constraint(output, {"Nodes": [21, 22]}, transform_obj, None)
            transform_outputs["cylindrical"] = output.getvalue()
        factory_results["transform_writer_outputs"] = transform_outputs
        transform_module = getattr(calculix, "write_constraint_transform")
        material_module = getattr(calculix, "write_femelement_material")
        for label, module in (("transform", transform_module), ("material", material_module)):
            try:
                source = inspect.getsource(module)
                factory_results[label + "_source_head"] = source[:6000]
            except Exception as exc:
                factory_results[label + "_source_head"] = {"error_type": type(exc).__name__}
        try:
            from femmesh import meshsetsgetter
            source = inspect.getsource(meshsetsgetter.MeshSetsGetter)
            factory_results["meshsets_source_head"] = source[:12000]
            getter_source = inspect.getsource(meshsetsgetter.MeshSetsGetter.get_element_sets_material_and_femelement_geometry)
            factory_results["meshsets_material_source"] = getter_source[:16000]
            grouping_methods = {}
            for method_name in (
                "get_material_elements",
                "get_element_geometry1D_elements",
                "get_element_geometry2D_elements",
                "get_mat_geo_sets_multiple_mat_multiple_beam",
                "get_mat_geo_sets_multiple_mat_multiple_shell",
            ):
                method = getattr(meshsetsgetter.MeshSetsGetter, method_name, None)
                if method is not None:
                    grouping_methods[method_name] = inspect.getsource(method)[:12000]
            factory_results["meshsets_grouping_methods"] = grouping_methods
            try:
                import femsolver.calculix.writer as writer
                factory_results["calculix_writer_names"] = sorted(
                    name for name in dir(writer)
                    if "write" in name.lower() or "writer" in name.lower() or "constraint" in name.lower()
                )
                factory_results["calculix_writer_source_head"] = inspect.getsource(writer)[:18000]
            except Exception as exc:
                factory_results["calculix_writer_error_type"] = type(exc).__name__
        except Exception as exc:
            factory_results["meshsets_source_head"] = {"error_type": type(exc).__name__}
        factory_results["writer_api"] = writer_api
        factory_results["writer_modules"] = writer_modules
        print(json.dumps(factory_results, sort_keys=True))
    finally:
        app.closeDocument(doc.Name)


run()
