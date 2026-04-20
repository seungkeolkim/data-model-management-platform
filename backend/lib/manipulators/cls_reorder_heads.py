"""
cls_reorder_heads — Classification 전용 Head 순서 변경 manipulator.

역할:
    head_schema 배열의 순서를 사용자가 지정한 순서대로 재정렬한다.
    merge 이전에 두 브랜치의 head 순서를 맞추기 위해 사용한다.

params:
    ordered_head_names:
        list[str] 또는 줄바꿈 구분 str. 기존 head 를 빠짐없이,
        중복 없이 포함해야 한다.

head_schema 만 변경되며 image_records[*].labels 는 dict 이라 순서 무관 → 수정 불요.
이미지 바이너리 불변 → file_name 유지 → lazy copy.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema

logger = logging.getLogger(__name__)


class ReorderHeadsClassification(UnitManipulator):
    """DB seed name: "cls_reorder_heads"."""

    REQUIRED_PARAMS = ["ordered_head_names"]

    @property
    def name(self) -> str:
        return "cls_reorder_heads"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise ValueError(
                "cls_reorder_heads 는 단일 입력만 지원합니다 (list 입력 불가)."
            )
        if input_meta.head_schema is None:
            raise ValueError(
                "cls_reorder_heads 는 classification DatasetMeta 에만 사용합니다 "
                "(head_schema 가 None 입니다)."
            )

        ordered_names = self._parse_ordered_names(params.get("ordered_head_names"))
        existing_head_names = [head.name for head in input_meta.head_schema]

        # 검증: 누락된 head 가 있으면 에러
        existing_set = set(existing_head_names)
        ordered_set = set(ordered_names)
        missing_from_order = existing_set - ordered_set
        if missing_from_order:
            raise ValueError(
                f"cls_reorder_heads: 다음 head 가 ordered_head_names 에 누락되었습니다: "
                f"{sorted(missing_from_order)}. 기존 head: {existing_head_names}"
            )

        # 검증: 존재하지 않는 head 이름이 있으면 에러
        unknown_names = ordered_set - existing_set
        if unknown_names:
            raise ValueError(
                f"cls_reorder_heads: 존재하지 않는 head 이름입니다: "
                f"{sorted(unknown_names)}. 기존 head: {existing_head_names}"
            )

        # 검증: 중복이 있으면 에러
        if len(ordered_names) != len(ordered_set):
            raise ValueError(
                f"cls_reorder_heads: ordered_head_names 에 중복이 있습니다: "
                f"{ordered_names}"
            )

        # head_schema 를 지정 순서대로 재정렬
        head_by_name = {head.name: head for head in input_meta.head_schema}
        new_head_schema = [
            HeadSchema(
                name=head_by_name[head_name].name,
                multi_label=head_by_name[head_name].multi_label,
                classes=list(head_by_name[head_name].classes),
            )
            for head_name in ordered_names
        ]

        # labels 는 dict 이라 순서 무관 → image_records 는 그대로 복제
        new_records = [
            replace(
                record,
                labels=dict(record.labels) if record.labels else {},
                extra=dict(record.extra) if record.extra else {},
            )
            for record in input_meta.image_records
        ]

        return DatasetMeta(
            dataset_id=input_meta.dataset_id,
            storage_uri=input_meta.storage_uri,
            categories=[],
            image_records=new_records,
            head_schema=new_head_schema,
            extra=dict(input_meta.extra) if input_meta.extra else {},
        )

    @staticmethod
    def _parse_ordered_names(raw_value: Any) -> list[str]:
        """params.ordered_head_names 를 list/str/None → list[str] 정규화."""
        if raw_value is None:
            raise ValueError("ordered_head_names 는 필수입니다.")
        if isinstance(raw_value, str):
            names = [line.strip() for line in raw_value.splitlines() if line.strip()]
            if not names:
                raise ValueError("ordered_head_names 가 비어있습니다.")
            return names
        if isinstance(raw_value, (list, tuple)):
            names = [str(item).strip() for item in raw_value if str(item).strip()]
            if not names:
                raise ValueError("ordered_head_names 가 비어있습니다.")
            return names
        raise ValueError(
            f"ordered_head_names 는 list 또는 str 이어야 합니다: "
            f"{type(raw_value).__name__}"
        )
