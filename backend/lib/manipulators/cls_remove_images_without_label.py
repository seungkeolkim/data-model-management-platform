"""
cls_remove_images_without_label — 라벨 없는 이미지 제거 manipulator (STUB).

역할:
    지정한 head(또는 모든 head)에 대해 label 이 없는(빈 리스트) 이미지를 image_records 에서 제거한다.
    multi_label head 에서 label 누락 상태를 정리할 때 주로 사용한다.

params:
    target_head_names: list[str] | None — None 이면 모든 head 기준. 리스트면 해당 head 들 중
                                            하나라도 label 이 없으면 제거 (AND 아닌 OR 조건).

이미지 바이너리 불변 → 남은 image_records 의 file_name 유지 → lazy copy.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class RemoveImagesWithoutLabelClassification(UnitManipulator):
    """DB seed name: "cls_remove_images_without_label"."""

    @property
    def name(self) -> str:
        return "cls_remove_images_without_label"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "cls_remove_images_without_label 는 아직 구현되지 않았습니다 (stub)."
        )
