"""
cls_add_head — 신규 Head 추가 manipulator (STUB).

역할:
    기존 classification 데이터셋에 새로운 head 를 추가한다. 추가되는 head 의 class 후보
    목록과 라벨 타입(single/multi) 을 params 로 받는다. 기존 이미지의 신규 head labels
    값은 모두 `null` (unknown) 으로 설정되며, §2-12 의 null=unknown 규약을 따른다.

params:
    head_name:        text     — 신규 head 이름. 기존 head 와 중복 금지.
    label_type:       select   — "single" | "multi". 기본 "single".
    class_candidates: textarea — Class 이름 목록 (줄바꿈 구분, 2개 이상).

head_schema 변경만 있고 이미지 바이너리 변형은 없으므로 file_name 유지 (lazy copy).

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class AddHeadClassification(UnitManipulator):
    """DB seed name: "cls_add_head"."""

    @property
    def name(self) -> str:
        return "cls_add_head"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "cls_add_head 는 아직 구현되지 않았습니다 (stub)."
        )
