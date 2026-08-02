"""Small result query/show pipeline for CalculiX artifacts."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


class PipelineError(RuntimeError):
    pass


class FemPostPipeline:
    """Read bounded numeric result artifacts without evaluating their text."""

    def __init__(self, app: Any = None, gui: Any = None, max_bytes: int = 16 * 1024 * 1024, max_rows: int = 4096):
        self.app, self.gui = app, gui
        self.max_bytes, self.max_rows = max_bytes, max_rows

    @staticmethod
    def _source(path: Any) -> Path:
        if not isinstance(path, str) or not path or len(path) > 2048 or "\x00" in path:
            raise PipelineError("result path is invalid")
        candidate = Path(path)
        if not candidate.is_absolute() or candidate.suffix.lower() not in {".frd", ".dat", ".csv", ".txt", ".vtk", ".vtm"} or not candidate.is_file():
            raise PipelineError("result artifact is invalid")
        if candidate.stat().st_size > 16 * 1024 * 1024:
            raise PipelineError("result artifact exceeds size limit")
        return candidate

    @staticmethod
    def _numbers(text: str) -> List[float]:
        values = []
        for token in text.replace(",", " ").split():
            try:
                value = float(token)
            except ValueError:
                continue
            if math.isfinite(value):
                values.append(value)
        return values

    def query(self, path: str, fields: Optional[Iterable[str]] = None, limit: int = 256) -> Dict[str, Any]:
        source = self._source(path)
        if not isinstance(limit, int) or not 1 <= limit <= self.max_rows:
            raise PipelineError("result row limit is invalid")
        requested = [field for field in (fields or []) if isinstance(field, str) and len(field) <= 64]
        rows = []
        with source.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, 1):
                if len(line.encode("utf-8", "replace")) > 8192:
                    continue
                numbers = self._numbers(line)
                if numbers:
                    rows.append({"line": line_number, "values": numbers[:64]})
                    if len(rows) >= limit:
                        break
        return {"path": str(source), "format": source.suffix.lower().lstrip("."), "fields": requested, "rows": rows, "truncated": len(rows) >= limit}

    @staticmethod
    def _pipeline(results: Any) -> Any:
        values = results if isinstance(results, (list, tuple)) else [results]
        for value in values:
            if getattr(value, "TypeId", "") == "Fem::FemPostPipeline":
                return value
        raise PipelineError("native FemPostPipeline result is unavailable")

    @staticmethod
    def _bounded_values(value: Any, limit: int = 8192) -> List[float]:
        result = []
        def visit(item: Any) -> None:
            if len(result) >= limit:
                return
            if isinstance(item, (int, float)) and math.isfinite(float(item)):
                result.append(float(item))
            elif isinstance(item, (list, tuple)):
                for child in item:
                    visit(child)
                    if len(result) >= limit:
                        return
        visit(value)
        return result

    @staticmethod
    def _normalise_field(value: Any) -> str:
        return "".join(character.lower() for character in str(value) if character.isalnum())

    def _vtk_blocks(self, data: Any) -> List[Any]:
        """Enumerate a vtkMultiBlockDataSet without importing VTK."""
        if data is None:
            return []
        get_blocks = getattr(data, "GetNumberOfBlocks", None)
        get_block = getattr(data, "GetBlock", None)
        if callable(get_blocks) and callable(get_block):
            blocks = []
            try:
                count = min(max(int(get_blocks()), 0), 256)
            except Exception:
                count = 0
            for index in range(count):
                try:
                    block = get_block(index)
                except Exception:
                    block = None
                if block is not None:
                    blocks.append(block)
            return blocks
        return [data]

    def _vtk_arrays(self, data: Any) -> List[tuple[str, Any]]:
        arrays: List[tuple[str, Any]] = []
        seen_arrays = set()
        for block in self._vtk_blocks(data):
            for association in ("GetPointData", "GetCellData"):
                attributes = getattr(block, association, None)
                attributes = attributes() if callable(attributes) else None
                if attributes is None:
                    continue
                get_count = getattr(attributes, "GetNumberOfArrays", None)
                get_array = getattr(attributes, "GetArray", None)
                if not callable(get_count) or not callable(get_array):
                    continue
                try:
                    count = min(max(int(get_count()), 0), 512)
                except Exception:
                    count = 0
                for index in range(count):
                    try:
                        array = get_array(index)
                        name_getter = getattr(array, "GetName", None)
                        name = name_getter() if callable(name_getter) else None
                        if name:
                            identity = (id(array), str(name))
                            if identity in seen_arrays:
                                continue
                            seen_arrays.add(identity)
                            arrays.append((str(name)[:128], array))
                    except (AttributeError, IndexError, TypeError, ValueError, RuntimeError):
                        continue
        return arrays

    def _native_fields(self, pipeline: Any, data: Any) -> tuple[List[str], List[tuple[str, Any]]]:
        arrays = self._vtk_arrays(data)
        names = [name for name, _array in arrays]
        view = getattr(pipeline, "ViewObject", None)
        enumerate_fields = getattr(view, "getEnumerationsOfProperty", None) if view is not None else None
        if callable(enumerate_fields):
            try:
                values = enumerate_fields("Field") or []
                names.extend(str(value)[:128] for value in list(values)[:256])
            except Exception:
                pass
        fields_value = getattr(pipeline, "Fields", getattr(pipeline, "FieldNames", []))
        if isinstance(fields_value, Mapping):
            names.extend(str(item)[:128] for item in list(fields_value.keys())[:256])
        elif isinstance(fields_value, (list, tuple)):
            names.extend(str(item)[:128] for item in list(fields_value)[:256])
        # Preserve order while bounding and deduplicating names.
        result = []
        seen = set()
        for name in names:
            key = self._normalise_field(name)
            if key and key not in seen:
                seen.add(key)
                result.append(name)
        return result[:256], arrays

    def _resolve_field(self, requested: Optional[str], fields: List[str]) -> Optional[str]:
        if requested is None:
            return None
        if not isinstance(requested, str) or len(requested) > 128:
            raise PipelineError("result field is invalid")
        wanted = self._normalise_field(requested)
        for name in fields:
            if self._normalise_field(name) == wanted:
                return name
        aliases = {
            "displacement": ("displacement", "disp", "u"),
            "stress": ("stress", "sigma"),
            "strain": ("strain", "epsilon"),
            "vonmises": ("vonmises", "mises", "equivalentstress"),
            "reaction": ("reaction", "force"),
        }
        for candidate in aliases.get(wanted, (wanted,)):
            for name in fields:
                if candidate in self._normalise_field(name):
                    return name
        raise PipelineError("result field is unavailable")

    def _vtk_extrema(self, arrays: List[tuple[str, Any]], selected: Optional[str], limit: int) -> Dict[str, Any]:
        values: List[float] = []
        tuple_count = 0
        selected_key = self._normalise_field(selected) if selected is not None else None
        alias_map = {
            "displacement": {"displacement", "disp", "u"},
            "stress": {"stress", "sigma"},
            "strain": {"strain", "epsilon"},
            "vonmises": {"vonmises", "mises", "equivalentstress"},
            "reaction": {"reaction", "force"},
        }
        alias_values = alias_map.get(selected_key, {selected_key} if selected_key is not None else set())
        if selected_key is not None and selected_key not in alias_map:
            for alias, candidates in alias_map.items():
                if alias in selected_key:
                    alias_values = candidates
                    break
        for name, array in arrays:
            if selected is not None and self._normalise_field(name) not in alias_values:
                continue
            get_tuples = getattr(array, "GetNumberOfTuples", None)
            get_tuple = getattr(array, "GetTuple", None)
            get_value = getattr(array, "GetValue", None)
            if not callable(get_tuples):
                continue
            try:
                count = min(max(int(get_tuples()), 0), limit)
            except (AttributeError, IndexError, TypeError, ValueError, RuntimeError):
                continue
            for index in range(count):
                try:
                    item = get_tuple(index) if callable(get_tuple) else get_value(index) if callable(get_value) else None
                except Exception:
                    item = None
                numbers = self._bounded_values(item, limit - len(values))
                values.extend(numbers)
                if numbers:
                    tuple_count += 1
                if len(values) >= limit:
                    break
            if len(values) >= limit:
                break
        return {"min": min(values), "max": max(values), "count": tuple_count} if values else {"min": None, "max": None, "count": 0}

    def query_native(self, results: Any, field: Optional[str] = None, frame: int = 0, limit: int = 8192) -> Dict[str, Any]:
        """Query a native pipeline's bounded fields/data and extrema."""
        if not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise PipelineError("result item limit is invalid")
        pipeline = self._pipeline(results)
        time_info = getattr(pipeline, "TimeInfo", getattr(pipeline, "TimeSteps", []))
        times = list(time_info or [])[:256] if isinstance(time_info, (list, tuple)) else []
        data = getattr(pipeline, "Data", getattr(pipeline, "Results", None))
        fields, arrays = self._native_fields(pipeline, data)
        resolved_field = self._resolve_field(field, fields)
        if arrays:
            extrema = self._vtk_extrema(arrays, resolved_field, limit)
            return {"type": "Fem::FemPostPipeline", "fields": fields, "times": times, "frame": frame, "field": resolved_field, "extrema": extrema}
        selected = data
        if isinstance(data, Mapping):
            if resolved_field is not None:
                selected = next((value for key, value in data.items() if self._normalise_field(key) == self._normalise_field(resolved_field)), [])
            else:
                selected = next(iter(data.values()), [])
        if isinstance(data, (list, tuple)) and data and isinstance(data[0], (list, tuple)):
            if not isinstance(frame, int) or not 0 <= frame < len(data):
                raise PipelineError("result frame is out of range")
            selected = data[frame]
        numbers = self._bounded_values(selected, limit)
        extrema = {"min": min(numbers), "max": max(numbers), "count": len(numbers)} if numbers else {"min": None, "max": None, "count": 0}
        return {"type": "Fem::FemPostPipeline", "fields": fields, "times": times, "frame": frame, "field": resolved_field, "extrema": extrema}

    def show_native(self, results: Any, field: Optional[str] = None, frame: int = 0, limit: int = 8192) -> Dict[str, Any]:
        pipeline = self._pipeline(results)
        summary = self.query_native([pipeline], field, frame, limit)
        view = getattr(pipeline, "ViewObject", None)
        if view is not None:
            if summary.get("field") is not None:
                try:
                    view.Field = summary["field"]
                except Exception:
                    pass
            for key, value in (("Frame", frame), ("Time", frame)):
                try:
                    setattr(view, key, value)
                except Exception:
                    pass
            try:
                view.DisplayMode = "Surface"
            except Exception:
                pass
        return {"shown": True, **summary}

    def show(self, results: Any, field: Optional[str] = None, frame: int = 0) -> Dict[str, Any]:
        """Show an already-imported native result pipeline."""
        return self.show_native(results, field, frame)
