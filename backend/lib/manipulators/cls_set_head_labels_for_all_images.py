"""
cls_set_head_labels_for_all_images — 특정 Head 의 labels 를 모든 이미지에서 일괄 덮어쓰기 (STUB).

역할:
    지정 head 의 labels 를 전체 이미지에서 동일 값으로 overwrite. 주요 용도 두 가지:
      1. head 전체를 unknown 으로 되돌리기 (action="set_null").
      2. 특정 class 조합으로 일괄 지정 (action="set_classes").

    single-label head 에 다수 class 를 넣으면 writer assert 에러가 난다(§2-12). 실구현
    단계에서 head_schema 의 multi_label 플래그와 classes 개수를 보고 미리 차단한다.

params:
    head_name: text      — 대상 head 이름.
    action:    select    — "set_null" | "set_classes". 기본 "set_null".
    classes:   textarea  — action="set_classes" 일 때 사용. 줄바꿈 구분.
                            single-label 이면 정확히 1줄, multi-label 이면 0줄 이상(빈 리스트 허용).

head_schema / file_name 변경 없음 (labels 만 overwrite) → lazy copy.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class SetHeadLabelsForAllImagesClassification(UnitManipulator):
    """DB seed name: "cls_set_head_labels_for_all_images"."""

    @property
    def name(self) -> str:
        return "cls_set_head_labels_for_all_images"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "cls_set_head_labels_for_all_images 는 아직 구현되지 않았습니다 (stub)."
        )
