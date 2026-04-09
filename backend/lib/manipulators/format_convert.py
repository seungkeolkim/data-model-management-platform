"""
포맷 변환 Manipulator (no-op).

통일포맷 전환으로 인해 내부에서 포맷 변환이 불필요해짐.
기존 파이프라인 정의/시각화 호환을 위해 registry에 유지하되, 입력을 그대로 반환한다.
실제 포맷 결정은 SaveNode의 output.annotation_format에서 이루어진다.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta

logger = logging.getLogger(__name__)


class FormatConvertToYolo(UnitManipulator):
    """
    COCO → YOLO 포맷 변환 (no-op).

    통일포맷에서는 내부적으로 포맷 구분이 없으므로 아무 변환도 수행하지 않는다.
    출력 포맷은 SaveNode에서 결정된다.

    DB seed name: "format_convert_to_yolo"
    """

    @property
    def name(self) -> str:
        return "format_convert_to_yolo"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise TypeError(
                "format_convert_to_yolo는 PER_SOURCE 전용입니다. "
                "단건 DatasetMeta만 입력 가능합니다."
            )
        logger.info(
            "format_convert_to_yolo: 통일포맷에서 no-op. "
            "출력 포맷은 Save 노드에서 결정됩니다."
        )
        return copy.deepcopy(input_meta)


class FormatConvertToCoco(UnitManipulator):
    """
    YOLO → COCO 포맷 변환 (no-op).

    통일포맷에서는 내부적으로 포맷 구분이 없으므로 아무 변환도 수행하지 않는다.
    출력 포맷은 SaveNode에서 결정된다.

    DB seed name: "format_convert_to_coco"
    """

    @property
    def name(self) -> str:
        return "format_convert_to_coco"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise TypeError(
                "format_convert_to_coco는 PER_SOURCE 전용입니다. "
                "단건 DatasetMeta만 입력 가능합니다."
            )
        logger.info(
            "format_convert_to_coco: 통일포맷에서 no-op. "
            "출력 포맷은 Save 노드에서 결정됩니다."
        )
        return copy.deepcopy(input_meta)
