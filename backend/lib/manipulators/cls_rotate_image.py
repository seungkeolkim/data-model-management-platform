"""
cls_rotate_image — 이미지 회전 manipulator (STUB).

역할:
    이미지를 90 / 180 / 270 도로 회전. det_rotate_image 와 동일 로직이나 classification
    자료구조(head_schema / labels) 에 대응한다. 라벨은 이미지 회전과 독립이므로 변경 없음.
    Phase B 실체화 시 이미지 바이너리 변형 + `record.file_name` 갱신이 필요하다.

params:
    degrees: select ("90" | "180" | "270") — 기본 "180".

v7.5 filename-identity 체계에서는 SHA 재계산이 불필요하다 (§2-13).

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class RotateImageClassification(UnitManipulator):
    """DB seed name: "cls_rotate_image"."""

    @property
    def name(self) -> str:
        return "cls_rotate_image"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "cls_rotate_image 는 아직 구현되지 않았습니다 (stub)."
        )
