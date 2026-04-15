"""
merge_classification_classes — 같은 Head 내 여러 Class 를 하나로 통합 (STUB).

역할:
    지정 head 의 여러 원본 class 를 하나의 target class 로 병합한다.
    예: {head: "vehicle", targets: ["sedan", "suv", "van"], merged_into: "car"}
    head.classes 에서 source class 를 제거하고 target 을 유지.
    image_records[*].labels[head] 의 해당 class 이름들을 target 으로 치환.
    multi_label head 의 경우 dedup 수행.

params:
    head_name:     str       — 대상 head 이름.
    source_classes: list[str] — 병합 대상 class 이름 목록.
    merged_into:   str       — 병합 후 class 이름 (source_classes 중 하나이거나 신규 이름).

이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class MergeClassificationClasses(UnitManipulator):
    """DB seed name: "merge_classification_classes"."""

    @property
    def name(self) -> str:
        return "merge_classification_classes"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "merge_classification_classes 는 아직 구현되지 않았습니다 (stub)."
        )
