"""
cls_select_heads — Classification 전용 Head 선택 manipulator.

역할:
    head_schema 에서 사용자가 지정한 head 만 유지하고 나머지는 제거한다.
    image_records[*].labels 에서도 선택되지 않은 head 키를 제거한다.

params:
    keep_head_names:
        list[str] 또는 줄바꿈 구분 str. 비어있거나 None 이면 모든 head 유지(= passthrough).
        지정된 head 이름 중 실제 존재하지 않는 것은 무시한다 (에러 내지 않고 로그만).

이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)


class SelectHeadsClassification(UnitManipulator):
    """DB seed name: "cls_select_heads"."""

    @property
    def name(self) -> str:
        return "cls_select_heads"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise ValueError(
                "cls_select_heads 는 단일 입력만 지원합니다 (list 입력 불가)."
            )
        if input_meta.head_schema is None:
            raise ValueError(
                "cls_select_heads 는 classification DatasetMeta 에만 사용합니다 "
                "(head_schema 가 None 입니다)."
            )

        keep_set = self._parse_keep_set(params.get("keep_head_names"))
        existing_head_names = [head.name for head in input_meta.head_schema]

        if not keep_set:
            # 빈 입력 = passthrough. head_schema/labels 그대로 복제.
            logger.info(
                "cls_select_heads: keep_head_names 비어있음 → 모든 head 유지 (passthrough)"
            )
            new_head_schema = [
                HeadSchema(name=head.name, multi_label=head.multi_label, classes=list(head.classes))
                for head in input_meta.head_schema
            ]
        else:
            missing_names = keep_set - set(existing_head_names)
            if missing_names:
                logger.warning(
                    "cls_select_heads: 존재하지 않는 head 는 무시 — missing=%s, existing=%s",
                    sorted(missing_names), existing_head_names,
                )
            new_head_schema = [
                HeadSchema(name=head.name, multi_label=head.multi_label, classes=list(head.classes))
                for head in input_meta.head_schema
                if head.name in keep_set
            ]
            if not new_head_schema:
                raise ValueError(
                    f"cls_select_heads: keep_head_names 와 매칭되는 head 가 없습니다. "
                    f"keep={sorted(keep_set)}, existing={existing_head_names}"
                )

        kept_head_names = {head.name for head in new_head_schema}
        new_records: list[ImageRecord] = []
        for record in input_meta.image_records:
            filtered_labels = {
                head_name: list(class_names)
                for head_name, class_names in (record.labels or {}).items()
                if head_name in kept_head_names
            }
            new_records.append(
                replace(
                    record,
                    labels=filtered_labels,
                    extra=dict(record.extra) if record.extra else {},
                )
            )

        return DatasetMeta(
            dataset_id=input_meta.dataset_id,
            storage_uri=input_meta.storage_uri,
            categories=[],
            image_records=new_records,
            head_schema=new_head_schema,
            extra=dict(input_meta.extra) if input_meta.extra else {},
        )

    @staticmethod
    def _parse_keep_set(raw_value: Any) -> set[str]:
        """params.keep_head_names 를 list/str/None 어느 쪽으로 들어와도 set[str] 로 정규화한다."""
        if raw_value is None:
            return set()
        if isinstance(raw_value, str):
            return {line.strip() for line in raw_value.splitlines() if line.strip()}
        if isinstance(raw_value, (list, tuple)):
            return {str(item).strip() for item in raw_value if str(item).strip()}
        raise ValueError(
            f"keep_head_names 는 list 또는 str 이어야 합니다: {type(raw_value).__name__}"
        )
