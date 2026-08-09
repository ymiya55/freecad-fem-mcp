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

    _MODE_MIN = 1
    _MODE_MAX = 100
    # These are the only native result links/properties inspected at this
    # boundary.  In particular, a client cannot name an arbitrary FreeCAD
    # property or execute a native method to obtain result data.
    _PIPELINE_LINKS = ("Pipeline", "PostPipeline", "ResultPipeline", "FemPostPipeline")
    _MODE_PROPERTIES = ("Eigenmode", "Mode")
    _FREQUENCY_PROPERTIES = ("EigenmodeFrequency",)

    @staticmethod
    def _values(results: Any) -> List[Any]:
        if results is None:
            return []
        if isinstance(results, (list, tuple)):
            return list(results)[:256]
        return [results]

    @staticmethod
    def _type_id(value: Any) -> str:
        return str(getattr(value, "TypeId", ""))

    @classmethod
    def _is_pipeline(cls, value: Any) -> bool:
        return cls._type_id(value) in {"Fem::FemPostPipeline", "Fem::FemPostPipelinePython"}

    @classmethod
    def _is_result_mechanical(cls, value: Any) -> bool:
        type_id = cls._type_id(value).lower()
        proxy_type = str(getattr(getattr(value, "Proxy", None), "Type", "")).lower()
        # FreeCAD 1.1's ObjectsFem factory returns Fem::FemResultObjectPython
        # with Proxy.Type == Fem::ResultMechanical.  Some releases expose a
        # native Fem::ResultMechanical TypeId instead.  Keep this allowlist
        # explicit; do not infer result objects from arbitrary properties.
        return proxy_type in {"fem::resultmechanical", "resultmechanical"} or type_id in {
            "fem::femresultmechanical", "fem::resultmechanical"
        }

    @classmethod
    def _pipeline(cls, results: Any) -> Any:
        values = cls._values(results)
        for value in values:
            if cls._is_pipeline(value):
                return value
        # A ResultMechanical may hold its native post pipeline as a link.  Do
        # not walk arbitrary attributes: only the documented link spellings
        # above are accepted.
        for value in values:
            if not cls._is_result_mechanical(value):
                continue
            for name in cls._PIPELINE_LINKS:
                try:
                    linked = getattr(value, name, None)
                except Exception:
                    linked = None
                if cls._is_pipeline(linked):
                    return linked
        raise PipelineError("native FemPostPipeline result is unavailable")

    @staticmethod
    def _finite_scalar(value: Any, name: str) -> float:
        """Convert a native scalar/quantity to finite JSON-safe float.

        FreeCAD quantities stringify as ``"12.3 Hz"`` while test doubles and
        some importer versions expose Python numbers.  Only the leading
        numeric token is accepted; arbitrary expressions or property objects
        are never evaluated.
        """

        if isinstance(value, bool) or value is None:
            raise PipelineError("{} is unavailable or non-finite".format(name))
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            text = str(value).strip()
            if not text or len(text) > 128:
                raise PipelineError("{} is unavailable or non-finite".format(name))
            token = text.split()[0]
            try:
                number = float(token)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PipelineError("{} is unavailable or non-finite".format(name)) from exc
        if not math.isfinite(number):
            raise PipelineError("{} is unavailable or non-finite".format(name))
        return number

    @classmethod
    def _mode_number(cls, result: Any) -> Optional[int]:
        for name in cls._MODE_PROPERTIES:
            try:
                value = getattr(result, name, None)
            except Exception:
                value = None
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            number = value
            if cls._MODE_MIN <= number <= cls._MODE_MAX:
                return number
            return None
        return None

    @classmethod
    def _mode_frequency(cls, result: Any) -> float:
        for name in cls._FREQUENCY_PROPERTIES:
            try:
                value = getattr(result, name, None)
            except Exception:
                value = None
            if value is not None:
                return cls._finite_scalar(value, name)
        raise PipelineError("EigenmodeFrequency is unavailable")

    @classmethod
    def available_modes(
        cls, results: Any, analysis_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return bounded native modal metadata, rejecting unsafe entries."""

        if analysis_type is not None and analysis_type not in {"frequency", "buckling"}:
            raise PipelineError("modal analysis type is unsupported")

        modes: List[Dict[str, Any]] = []
        seen: set[int] = set()
        values = cls._values(results)
        pipeline = next((value for value in values if cls._is_pipeline(value)), None)
        for result in values:
            if not cls._is_result_mechanical(result):
                continue
            mode = cls._mode_number(result)
            if mode is None:
                # ResultMechanical objects without Eigenmode are static
                # results and are not candidates for a modal query.
                continue
            if mode in seen:
                raise PipelineError("duplicate native Eigenmode {}".format(mode))
            seen.add(mode)
            frequency = cls._mode_frequency(result)
            if frequency <= 0.0:
                raise PipelineError("Eigenmode {} is a rigid mode".format(mode))
            # Frequency imports map mode N to Data block N-1.  Buckling
            # imports retain the static preload as block/frame zero, so the
            # first eigenmode is block/frame one instead.
            block_index = mode if analysis_type == "buckling" else mode - 1
            modes.append({"mode": mode, "frequency_hz": frequency, "result": result, "pipeline": pipeline, "block_index": block_index})
        # The CalculiX 1.1.3 importer returns one FemPostPipeline plus a text
        # document, not one ResultMechanical per mode.  Its native Frame
        # enumeration stores each eigenfrequency/buckling factor in order and
        # its vtkMultiBlockDataSet stores the corresponding mode in the same
        # bounded order.  This is the primary modal path for current builds.
        if not modes and pipeline is not None:
            enumerate_frames = getattr(pipeline, "getEnumerationsOfProperty", None)
            try:
                frame_values = enumerate_frames("Frame") if callable(enumerate_frames) else []
            except Exception:
                frame_values = []
            if not isinstance(frame_values, (list, tuple)):
                frame_values = []
            frame_values = list(frame_values)[: cls._MODE_MAX + 1]
            # CalculiX buckling imports include the preload/static state at
            # Frame[0] (factor 0.00); frequency imports start directly at mode
            # 1.  Keep this native ordering instead of parsing the companion
            # text document.
            offset = 0
            if analysis_type == "buckling" and frame_values:
                try:
                    offset = 1 if cls._finite_scalar(frame_values[0], "buckling factor") <= 0.0 else 0
                except PipelineError:
                    offset = 0
            for frame_index in range(offset, len(frame_values)):
                frame_value = frame_values[frame_index]
                mode = frame_index - offset + 1
                frequency = cls._finite_scalar(frame_value, "EigenmodeFrequency")
                if frequency <= 0.0:
                    if analysis_type == "buckling":
                        raise PipelineError("buckling mode {} has a non-positive factor".format(mode))
                    raise PipelineError("Eigenmode {} is a rigid mode".format(mode))
                modes.append(
                    {
                        "mode": mode,
                        "frequency_hz": frequency,
                        "result": pipeline,
                        "pipeline": pipeline,
                        "block_index": frame_index,
                        "frame_value": str(frame_value),
                    }
                )
        modes.sort(key=lambda item: item["mode"])
        return modes

    @classmethod
    def select_mode(
        cls, results: Any, mode: Any, analysis_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Select one native ResultMechanical mode using a closed schema."""

        if isinstance(mode, bool) or not isinstance(mode, int) or not cls._MODE_MIN <= mode <= cls._MODE_MAX:
            raise PipelineError("mode is outside the allowed range")
        modes = cls.available_modes(results, analysis_type)
        selected = next((item for item in modes if item["mode"] == mode), None)
        if selected is None:
            available = ", ".join(str(item["mode"]) for item in modes)
            suffix = "" if not available else "; available modes: " + available
            raise PipelineError("mode {} is unavailable{}".format(mode, suffix))
        result = selected["result"]
        pipeline = cls._pipeline_from_result(result)
        if selected.get("pipeline") is None:
            selected["pipeline"] = pipeline
        return {**selected, "pipeline": pipeline}

    @classmethod
    def _pipeline_from_result(cls, result: Any) -> Any:
        if cls._is_pipeline(result):
            return result
        for name in cls._PIPELINE_LINKS:
            try:
                linked = getattr(result, name, None)
            except Exception:
                linked = None
            if cls._is_pipeline(linked):
                return linked
        raise PipelineError("native FemPostPipeline result is unavailable for Eigenmode")

    @staticmethod
    def _mode_metadata(mode_info: Mapping[str, Any], analysis_type: Optional[str]) -> Dict[str, Any]:
        """Build stable modal metadata without conflating frequency/buckling."""

        mode = int(mode_info["mode"])
        value = float(mode_info["frequency_hz"])
        metadata: Dict[str, Any] = {"mode": mode}
        if analysis_type == "buckling":
            metadata["buckling_factor"] = value
        else:
            # A direct pipeline caller has no solver object from which to
            # recover AnalysisType; frequency is the historical/default modal
            # interpretation.  The service always supplies the native type,
            # so buckling results use buckling_factor there.
            metadata["frequency_hz"] = value
        return metadata

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

    def _vtk_blocks(self, data: Any, block_index: Optional[int] = None) -> List[Any]:
        """Enumerate a vtkMultiBlockDataSet without importing VTK.

        ``block_index`` is used only for the native modal importer where each
        block is one Eigenmode.  Static pipelines continue to expose every
        physical block exactly as before.
        """
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
            indices = [block_index] if block_index is not None and 0 <= block_index < count else range(count)
            for index in indices:
                if index is None:
                    continue
                try:
                    block = get_block(index)
                except Exception:
                    block = None
                if block is not None:
                    blocks.append(block)
            return blocks
        return [data]

    def _vtk_arrays(self, data: Any, block_index: Optional[int] = None) -> List[tuple[str, Any]]:
        arrays: List[tuple[str, Any]] = []
        seen_arrays = set()
        for block in self._vtk_blocks(data, block_index):
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

    @staticmethod
    def _frame_count(pipeline: Any, data: Any, times: List[Any]) -> int:
        """Infer a bounded frame count from native FemPostPipeline metadata."""

        for name in ("FrameCount", "NumberOfFrames"):
            try:
                value = getattr(pipeline, name, None)
                if value is not None:
                    count = int(value)
                    if count >= 1:
                        return min(count, 100001)
            except (TypeError, ValueError, OverflowError):
                pass
        if times:
            return min(len(times), 100001)
        enumerate_frames = getattr(pipeline, "getEnumerationsOfProperty", None)
        if callable(enumerate_frames):
            try:
                values = enumerate_frames("Frame") or []
                if isinstance(values, (list, tuple)) and values:
                    return min(len(values), 100001)
            except Exception:
                pass
        for name in ("Frames", "TimeSteps"):
            try:
                value = getattr(pipeline, name, None)
                if isinstance(value, (list, tuple)) and value:
                    return min(len(value), 100001)
            except Exception:
                pass
        # A pure-Python test double may represent frame data as a list.  VTK
        # multiblock datasets are intentionally not interpreted as frames:
        # their blocks are physical regions of one selected frame.
        if isinstance(data, (list, tuple)) and data and isinstance(data[0], (list, tuple)):
            return min(len(data), 100001)
        return 1

    @staticmethod
    def _frame_values(pipeline: Any) -> List[str]:
        enumerate_frames = getattr(pipeline, "getEnumerationsOfProperty", None)
        if not callable(enumerate_frames):
            return []
        try:
            values = enumerate_frames("Frame") or []
        except Exception:
            return []
        if not isinstance(values, (list, tuple)):
            return []
        return [str(value)[:128] for value in list(values)[:100001]]

    @staticmethod
    def _set_frame(pipeline: Any, frame: int) -> None:
        """Set the native pipeline frame through its documented properties."""

        # A FemPostPipeline's frame is a view/data selection, not a client
        # supplied property name.  Probe only the native Frame/Time spellings.
        frame_value = None
        enumerate_frames = getattr(pipeline, "getEnumerationsOfProperty", None)
        if callable(enumerate_frames):
            try:
                values = enumerate_frames("Frame") or []
                if isinstance(values, (list, tuple)) and 0 <= frame < len(values):
                    frame_value = values[frame]
            except Exception:
                pass
        value = frame_value if frame_value is not None else frame
        for target in (pipeline, getattr(pipeline, "ViewObject", None)):
            if target is None:
                continue
            for name in ("Frame", "Time"):
                try:
                    if hasattr(target, name):
                        setattr(target, name, value)
                except Exception:
                    pass

    @staticmethod
    def _set_frame_value(pipeline: Any, value: str) -> None:
        """Select one native Frame enumeration value."""

        try:
            if hasattr(pipeline, "Frame"):
                pipeline.Frame = value
        except Exception as exc:
            raise PipelineError("native result frame is unavailable") from exc

    def query_native(
        self,
        results: Any,
        field: Optional[str] = None,
        frame: int = 0,
        limit: int = 8192,
        *,
        mode: Optional[int] = None,
        analysis_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query a native pipeline's bounded fields/data and extrema.

        ``mode`` selects a native ResultMechanical object by its Eigenmode;
        leaving it ``None`` preserves the historical static-pipeline route.
        """
        if not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise PipelineError("result item limit is invalid")
        if analysis_type is not None and analysis_type not in {"static", "frequency", "buckling"}:
            raise PipelineError("analysis type is unsupported")
        if isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame <= 100000:
            raise PipelineError("result frame is out of range")
        if mode is not None and frame != 0:
            raise PipelineError("mode and nonzero frame cannot be combined")
        mode_info: Optional[Dict[str, Any]] = None
        if mode is None:
            pipeline = self._pipeline(results)
        else:
            mode_info = self.select_mode(results, mode, analysis_type)
            pipeline = mode_info["pipeline"]
        time_info = getattr(pipeline, "TimeInfo", getattr(pipeline, "TimeSteps", []))
        times = list(time_info or [])[:256] if isinstance(time_info, (list, tuple)) else []
        data = getattr(pipeline, "Data", getattr(pipeline, "Results", None))
        frame_count = self._frame_count(pipeline, data, times)
        if frame >= frame_count:
            raise PipelineError("result frame is out of range")
        frame_values = self._frame_values(pipeline)
        if mode_info is not None and mode_info.get("frame_value") is not None:
            self._set_frame_value(pipeline, mode_info["frame_value"])
        elif frame_values:
            self._set_frame_value(pipeline, frame_values[frame])
        block_index = mode_info.get("block_index") if mode_info is not None else None
        if block_index is not None:
            block_count_getter = getattr(data, "GetNumberOfBlocks", None)
            if callable(block_count_getter):
                try:
                    block_count = int(block_count_getter())
                except (TypeError, ValueError, OverflowError):
                    block_count = 0
                if not 0 <= int(block_index) < block_count:
                    raise PipelineError("mode {} has no imported frame".format(mode_info["mode"]))
        fields, arrays = self._native_fields(pipeline, data)
        if arrays and block_index is not None:
            arrays = self._vtk_arrays(data, int(block_index))
        resolved_field = self._resolve_field(field, fields)
        if arrays:
            extrema = self._vtk_extrema(arrays, resolved_field, limit)
            summary = {"type": "Fem::FemPostPipeline", "fields": fields, "times": times, "frame": frame, "field": resolved_field, "extrema": extrema}
            if mode_info is not None:
                summary.update(self._mode_metadata(mode_info, analysis_type))
            return summary
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
        summary = {"type": "Fem::FemPostPipeline", "fields": fields, "times": times, "frame": frame, "field": resolved_field, "extrema": extrema}
        if mode_info is not None:
            summary.update(self._mode_metadata(mode_info, analysis_type))
        return summary

    def show_native(
        self,
        results: Any,
        field: Optional[str] = None,
        frame: int = 0,
        limit: int = 8192,
        *,
        mode: Optional[int] = None,
        analysis_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        mode_info = self.select_mode(results, mode, analysis_type) if mode is not None else None
        pipeline = mode_info["pipeline"] if mode_info is not None else self._pipeline(results)
        summary = self.query_native(
            results, field, frame, limit, mode=mode, analysis_type=analysis_type
        )
        view = getattr(pipeline, "ViewObject", None)
        if view is not None:
            if summary.get("field") is not None:
                try:
                    view.Field = summary["field"]
                except Exception:
                    pass
            # ``query_native`` has already selected the modal Frame enum.
            # Assigning the public frame index here would reset mode N>1 to
            # frame zero on native ViewObjects, so leave both selectors alone
            # for modal requests.  Static callers retain the historical view
            # frame/time assignment.
            if mode is None:
                for key, value in (("Frame", frame), ("Time", frame)):
                    try:
                        setattr(view, key, value)
                    except Exception:
                        pass
            try:
                view.DisplayMode = "Surface"
            except Exception:
                pass
        # Do not overwrite a modal selection with frame=0.  The native
        # importer maps mode N to its Nth Frame enum value; query_native has
        # already selected and validated that value.
        if mode is None:
            self._set_frame(pipeline, frame)
        return {"shown": True, **summary}

    def show(
        self,
        results: Any,
        field: Optional[str] = None,
        frame: int = 0,
        *,
        mode: Optional[int] = None,
        analysis_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Show an already-imported native result pipeline."""
        return self.show_native(results, field, frame, mode=mode, analysis_type=analysis_type)
