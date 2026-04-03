"""
Manipulator 레지스트리.

name → UnitManipulator 클래스 매핑.
PipelineExecutor가 config의 manipulator_name으로 클래스를 조회할 때 사용한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from lib.manipulators.format_convert import FormatConvertToCoco, FormatConvertToYolo

if TYPE_CHECKING:
    from lib.pipeline.manipulator import UnitManipulator

MANIPULATOR_REGISTRY: dict[str, type[UnitManipulator]] = {
    "format_convert_to_coco": FormatConvertToCoco,
    "format_convert_to_yolo": FormatConvertToYolo,
}
