"""Contract tests for native frequency/buckling mode selection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "addon"))

from FreeCADFEMMCP.pipeline import FemPostPipeline, PipelineError  # noqa: E402


class _Array:
    def __init__(self, name: str, values: list[tuple[float, ...]]) -> None:
        self._name, self._values = name, values

    def GetName(self) -> str:
        return self._name

    def GetNumberOfTuples(self) -> int:
        return len(self._values)

    def GetTuple(self, index: int) -> tuple[float, ...]:
        return self._values[index]


class _Attributes:
    def __init__(self, arrays: list[_Array]) -> None:
        self._arrays = arrays

    def GetNumberOfArrays(self) -> int:
        return len(self._arrays)

    def GetArray(self, index: int) -> _Array:
        return self._arrays[index]


class _Block:
    def __init__(self, marker: float) -> None:
        self._attrs = _Attributes([_Array("Displacement", [(marker, marker + 1.0, marker + 2.0)])])

    def GetPointData(self) -> _Attributes:
        return self._attrs

    def GetCellData(self) -> _Attributes:
        return _Attributes([])


class _Blocks:
    def __init__(self, blocks: list[_Block]) -> None:
        self._blocks = blocks

    def GetNumberOfBlocks(self) -> int:
        return len(self._blocks)

    def GetBlock(self, index: int) -> _Block:
        return self._blocks[index]


class _View:
    Field = None


class _ModalPipeline:
    TypeId = "Fem::FemPostPipeline"

    def __init__(self, frames: list[str]) -> None:
        self.Frame = frames[0]
        self.Data = _Blocks([_Block(float(index + 1)) for index in range(len(frames))])
        self.ViewObject = _View()
        self._frames = frames

    def getEnumerationsOfProperty(self, name: str) -> list[str]:
        return list(self._frames) if name == "Frame" else []


def test_frequency_modes_map_native_frame_enum_and_data_block() -> None:
    native = _ModalPipeline(["10.0", "20.0"])
    summary = FemPostPipeline().query_native([native], "displacement", mode=2, limit=16)
    assert summary["mode"] == 2
    assert summary["frequency_hz"] == 20.0
    assert summary["extrema"] == {"min": 2.0, "max": 4.0, "count": 1}
    assert native.Frame == "20.0"


def test_buckling_skips_preload_frame_and_uses_factor_key() -> None:
    native = _ModalPipeline(["0.00", "43.10", "91.25"])
    summary = FemPostPipeline().query_native(
        [native], "displacement", mode=1, limit=16, analysis_type="buckling"
    )
    assert summary["mode"] == 1
    assert summary["buckling_factor"] == 43.1
    assert "frequency_hz" not in summary
    assert summary["extrema"]["min"] == 2.0
    assert native.Frame == "43.10"


def test_rigid_and_missing_modes_are_diagnosed() -> None:
    with pytest.raises(PipelineError, match="rigid mode"):
        FemPostPipeline().available_modes([_ModalPipeline(["0.0", "10.0"])])
    with pytest.raises(PipelineError, match="mode 3 is unavailable"):
        FemPostPipeline().query_native(
            [_ModalPipeline(["10.0", "20.0"])], mode=3, limit=16
        )


def test_mode_and_nonzero_frame_are_not_ambiguous() -> None:
    with pytest.raises(PipelineError, match="cannot be combined"):
        FemPostPipeline().query_native(
            [_ModalPipeline(["10.0", "20.0"])], mode=1, frame=1, limit=16
        )
