"""
cls_reorder_classes — 특정 Head 내 Class 순서 변경 manipulator (STUB).

역할:
    지정 head 의 classes 배열 순서를 사용자가 지정한 순서대로 재정렬한다.
    **주의**: classes 순서는 학습 모델 output index 의 SSOT 이므로 reorder 는
    파이프라인에서 유일하게 허용되는 순서 변경 경로다. merge 충돌 회피 목적으로 사용한다.

params:
    head_name:      str       — 대상 head 이름.
    ordered_classes: list[str] — 새 순서. 기존 classes 를 빠짐없이 포함해야 한다.

image_records[*].labels 는 dict[list] 이므로 순서 무관 → 수정 불요.
이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class ClsReorderClasses(UnitManipulator):
    """DB seed name: "cls_reorder_classes"."""

    @property
    def name(self) -> str:
        return "cls_reorder_classes"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "cls_reorder_classes 는 아직 구현되지 않았습니다 (stub)."
        )
