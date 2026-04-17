"""
cls_reorder_classes — 특정 Head 내 Class 순서 변경 manipulator.

역할:
    지정 head 의 classes 배열 순서를 사용자가 지정한 순서대로 재정렬한다.

**주의**: classes 순서는 학습 모델 output index 의 SSOT 이다. reorder 는
파이프라인에서 유일하게 허용되는 순서 변경 경로이며, 주로 merge 전 두
브랜치의 class 순서를 맞추기 위해 사용한다.

params:
    head_name:       str       — 대상 head 이름 (필수).
    ordered_classes: list[str] 또는 줄바꿈 구분 str — 새 순서. 기존 classes 를
        빠짐없이, 중복 없이 포함해야 한다.

image_records[*].labels 는 dict[head_name → list[class_name]] 이므로 순서 무관
→ labels 는 얕게 복제만. 다른 head 는 불변.
이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)


class ReorderClassesClassification(UnitManipulator):
    """DB seed name: "cls_reorder_classes"."""

    REQUIRED_PARAMS = ["head_name", "ordered_classes"]

    @property
    def name(self) -> str:
        return "cls_reorder_classes"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_reorder_classes 는 단일 입력만 지원합니다 (list 입력 불가)."
            )
        if input_meta.head_schema is None:
            raise ValueError(
                "cls_reorder_classes 는 classification DatasetMeta 에만 사용합니다 "
                "(head_schema 가 None 입니다)."
            )

        target_head_name = params.get("head_name")
        if not isinstance(target_head_name, str) or not target_head_name.strip():
            raise ValueError(
                "head_name 이 비어있습니다. 대상 Head 이름을 지정하세요."
            )
        target_head_name = target_head_name.strip()

        ordered_class_names = self._parse_ordered_classes(params.get("ordered_classes"))

        # 대상 head 찾기.
        existing_head_names = [head.name for head in input_meta.head_schema]
        target_head: HeadSchema | None = next(
            (head for head in input_meta.head_schema if head.name == target_head_name),
            None,
        )
        if target_head is None:
            raise ValueError(
                f"cls_reorder_classes: head_name='{target_head_name}' 가 head_schema 에 "
                f"없습니다. 존재하는 head: {existing_head_names}"
            )

        # 검증: 중복
        if len(ordered_class_names) != len(set(ordered_class_names)):
            duplicates = sorted(
                {name for name in ordered_class_names if ordered_class_names.count(name) > 1}
            )
            raise ValueError(
                f"cls_reorder_classes: ordered_classes 에 중복이 있습니다: {duplicates}"
            )

        existing_class_set = set(target_head.classes)
        ordered_class_set = set(ordered_class_names)

        # 검증: 누락 (기존 class 가 새 순서에 빠짐)
        missing_from_order = existing_class_set - ordered_class_set
        if missing_from_order:
            raise ValueError(
                f"cls_reorder_classes: 다음 class 가 ordered_classes 에 누락되었습니다: "
                f"{sorted(missing_from_order)}. head '{target_head_name}' 의 기존 "
                f"classes: {list(target_head.classes)}"
            )

        # 검증: 존재하지 않는 이름
        unknown_class_names = ordered_class_set - existing_class_set
        if unknown_class_names:
            raise ValueError(
                f"cls_reorder_classes: 존재하지 않는 class 이름입니다: "
                f"{sorted(unknown_class_names)}. head '{target_head_name}' 의 기존 "
                f"classes: {list(target_head.classes)}"
            )

        # head_schema 재구성 — 대상 head 만 순서 교체, 나머지는 얕은 복제.
        new_head_schema = [
            HeadSchema(
                name=head.name,
                multi_label=head.multi_label,
                classes=(
                    list(ordered_class_names)
                    if head.name == target_head_name
                    else list(head.classes)
                ),
            )
            for head in input_meta.head_schema
        ]

        # labels 는 dict[head → list[class] | None] 순서 무관 → 얕게 복제만.
        # None(unknown) 은 그대로 유지. §2-12 확정 규약.
        new_records: list[ImageRecord] = [
            replace(
                record,
                labels={
                    head_name: (list(class_names) if class_names is not None else None)
                    for head_name, class_names in (record.labels or {}).items()
                },
                extra=dict(record.extra) if record.extra else {},
            )
            for record in input_meta.image_records
        ]

        logger.info(
            "cls_reorder_classes 완료: head='%s' classes 순서 변경 %s → %s",
            target_head_name,
            list(target_head.classes),
            list(ordered_class_names),
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
    def _parse_ordered_classes(raw_value: Any) -> list[str]:
        """params.ordered_classes 를 list/str/None → list[str] 정규화."""
        if raw_value is None:
            raise ValueError("ordered_classes 는 필수입니다.")
        if isinstance(raw_value, str):
            names = [line.strip() for line in raw_value.splitlines() if line.strip()]
            if not names:
                raise ValueError("ordered_classes 가 비어있습니다.")
            return names
        if isinstance(raw_value, (list, tuple)):
            names = [str(item).strip() for item in raw_value if str(item).strip()]
            if not names:
                raise ValueError("ordered_classes 가 비어있습니다.")
            return names
        raise ValueError(
            f"ordered_classes 는 list 또는 str 이어야 합니다: "
            f"{type(raw_value).__name__}"
        )
