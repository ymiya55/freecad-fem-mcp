"""FreeCAD 1.1.3 native R7.5 tie/contact and post-result audit.

This probe only inspects native FEM objects and CalculiX/FemPost APIs.  It does
not run a solver, inject an input deck, or use a legacy solver module.
"""

from __future__ import annotations

import inspect
import json
from typing import Any


def _properties(obj: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in getattr(obj, "PropertiesList", []) or []:
        try:
            values[str(name)] = str(obj.getTypeIdOfProperty(name))
        except Exception:
            values[str(name)] = "<unavailable>"
    return values


def _factory_names(objects_fem: Any, *needles: str) -> list[str]:
    return sorted(
        name
        for name in dir(objects_fem)
        if all(needle.lower() in name.lower() for needle in needles)
    )


def _module_names(package: Any, *needles: str) -> list[str]:
    return sorted(
        name
        for name in dir(package)
        if all(needle.lower() in name.lower() for needle in needles)
    )


def _callable_signatures(module: Any, names: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        candidate = getattr(module, name, None)
        if callable(candidate):
            try:
                result[name] = str(inspect.signature(candidate))
            except (TypeError, ValueError):
                result[name] = "<signature unavailable>"
    return result


def _try_factory(doc: Any, objects_fem: Any, name: str) -> dict[str, Any]:
    factory = getattr(objects_fem, name, None)
    if not callable(factory):
        return {"available": False}
    try:
        obj = factory(doc, name.removeprefix("make"))
    except Exception as exc:
        return {"available": True, "created": False, "error_type": type(exc).__name__}
    return {
        "available": True,
        "created": True,
        "type_id": str(getattr(obj, "TypeId", "")),
        "proxy_type": str(getattr(getattr(obj, "Proxy", None), "Type", "")),
        "properties": _properties(obj),
    }


def run() -> None:
    try:
        import FreeCAD as app  # type: ignore
        import ObjectsFem  # type: ignore
        import femsolver.calculix as calculix  # type: ignore
        import femsolver.calculix.writer as writer  # type: ignore
        import femtools.membertools as membertools  # type: ignore
        import femmesh.meshsetsgetter as meshsetsgetter  # type: ignore
        import femmesh.meshtools as meshtools  # type: ignore
    except ImportError as exc:
        raise SystemExit("run this probe with FreeCADCmd 1.1.3") from exc
    if getattr(app, "_R7NativeTieContactAuditRunning", False):
        return
    app._R7NativeTieContactAuditRunning = True
    doc = app.newDocument("R7TieContactAudit")
    try:
        result: dict[str, Any] = {
            "version": ".".join(str(part) for part in app.Version()),
            "tie_factories": _factory_names(ObjectsFem, "constraint", "tie"),
            "contact_factories": _factory_names(ObjectsFem, "constraint", "contact"),
            "result_factories": _factory_names(ObjectsFem, "result"),
            "post_factories": _factory_names(ObjectsFem, "post"),
            "calculix_tie_names": _module_names(calculix, "tie"),
            "calculix_contact_names": _module_names(calculix, "contact"),
            "writer_connection_names": _module_names(writer, "constraint"),
            "writer_connection_signatures": _callable_signatures(
                writer,
                (
                    "write_constraint_tie",
                    "write_constraint_contact",
                    "write_femelement_tie",
                    "write_femelement_contact",
                ),
            ),
            "membertools_connection_names": _module_names(membertools, "connection"),
            "meshsets_connection_names": _module_names(meshsetsgetter, "connection"),
            "meshtools_connection_names": _module_names(meshtools, "ccx"),
            "native_tie": _try_factory(doc, ObjectsFem, "makeConstraintTie"),
            "native_contact": _try_factory(doc, ObjectsFem, "makeConstraintContact"),
        }
        tie = doc.getObject("ConstraintTie")
        contact = doc.getObject("ConstraintContact")
        if tie is not None:
            try:
                result["native_tie"]["references_type"] = tie.getTypeIdOfProperty("References")
                result["native_tie"]["tolerance_default"] = str(tie.Tolerance)
                result["native_tie"]["adjust_default"] = str(tie.Adjust)
                result["native_tie"]["cyclic_default"] = str(tie.CyclicSymmetry)
            except Exception:
                pass
        if contact is not None:
            try:
                result["native_contact"]["references_type"] = contact.getTypeIdOfProperty("References")
                result["native_contact"]["surface_enums"] = contact.getEnumerationsOfProperty("SurfaceBehavior")
                result["native_contact"]["friction_default"] = str(contact.Friction)
                result["native_contact"]["thermal_default"] = str(contact.EnableThermalContact)
            except Exception:
                pass

        for factory_name in (
            "makeFemPostPipeline",
            "makeResultMechanical",
            "makeFemResultMechanical",
            "makeFemPostObject",
            "makeFemPostData",
        ):
            result.setdefault("post_objects", {})[factory_name] = _try_factory(doc, ObjectsFem, factory_name)
        result["post_generic"] = {}
        for type_id in ("Fem::FemPostPipeline", "Fem::FemPostPipelinePython", "Fem::FemResultObjectPython"):
            try:
                obj = doc.addObject(type_id, type_id.replace("::", "_"))
            except Exception as exc:
                result["post_generic"][type_id] = {"created": False, "error_type": type(exc).__name__}
                continue
            result["post_generic"][type_id] = {
                "created": True,
                "type_id": str(getattr(obj, "TypeId", "")),
                "proxy_type": str(getattr(getattr(obj, "Proxy", None), "Type", "")),
                "properties": _properties(obj),
            }
            for name in ("Data", "Results", "Pipeline", "PostPipeline", "Eigenmode", "EigenmodeFrequency", "Frame", "TimeInfo", "Fields"):
                try:
                    value = getattr(obj, name)
                    result["post_generic"][type_id].setdefault("values", {})[name] = {
                        "type": type(value).__name__,
                        "repr": str(value)[:256],
                    }
                except Exception:
                    pass
        for source_name, source_object in (
            ("AnalysisMember", getattr(membertools, "AnalysisMember", None)),
            ("MeshSetsGetter", getattr(meshsetsgetter, "MeshSetsGetter", None)),
        ):
            if source_object is None:
                continue
            try:
                result.setdefault("member_mesh_sources", {})[source_name] = inspect.getsource(source_object)[:18000]
            except (OSError, TypeError):
                pass
        for source_name in ("get_ccx_elements", "pair_obj_reference", "get_femnodes_by_femobj_with_references"):
            function = getattr(meshtools, source_name, None)
            if callable(function):
                try:
                    result.setdefault("meshtools_sources", {})[source_name] = inspect.getsource(function)[:12000]
                except (OSError, TypeError):
                    pass
        for module_name in ("write_constraints", "write_constraint_tie", "write_constraint_contact"):
            try:
                module = __import__("femsolver.calculix." + module_name, fromlist=[module_name])
                public_names = sorted(name for name in dir(module) if not name.startswith("_"))
                result.setdefault("writer_modules", {})[module_name] = {
                    "names": public_names[:256],
                    "signatures": _callable_signatures(module, tuple(public_names[:256])),
                }
                for source_name in public_names[:256]:
                    function = getattr(module, source_name, None)
                    if callable(function):
                        try:
                            result.setdefault("writer_sources", {})[module_name + ":" + source_name] = inspect.getsource(function)[:6000]
                        except (OSError, TypeError):
                            pass
            except Exception as exc:
                result.setdefault("writer_modules", {})[module_name] = {"error_type": type(exc).__name__}
        print(json.dumps(result, sort_keys=True))
    finally:
        app.closeDocument(doc.Name)


run()
