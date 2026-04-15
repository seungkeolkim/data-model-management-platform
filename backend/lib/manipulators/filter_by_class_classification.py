"""
filter_by_class_classification — 특정 Head 의 특정 Class 포함/제외 필터 (STUB).

역할:
    지정 head 의 특정 class 를 포함하거나 제외하는 필터.
    포함 모드: 지정 class label 을 가진 이미지만 유지.
    제외 모드: 지정 class label 을 가진 이미지 drop.
    head.classes 에서 제거된 class 도 함께 정리한다 (제외 모드에서 해당 class 가 완전히 사라지면).

params:
    head_name:      str       — 대상 head 이름.
    class_names:    list[str] — 필터 대상 class 이름 목록.
    mode:           "include" | "exclude" — 기본 "include".

이미지 바이너리 불변 → 남은 image_records 의 sha/file_name 유지 → lazy copy.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class FilterByClassClassification(UnitManipulator):
    """DB seed name: "filter_by_class_classification"."""

    @property
    def name(self) -> str:
        return "filter_by_class_classification"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "filter_by_class_classification 는 아직 구현되지 않았습니다 (stub)."
        )
