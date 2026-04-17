"""
cls_rename_class — 특정 Head 내 Class 이름 변경 manipulator.

역할:
    지정 head 의 classes 배열 내 이름을 매핑에 따라 변경한다.
    해당 head 의 image_records[*].labels[head_name] 내 class 이름도 함께 변경한다.
    classes 순서와 head_schema 다른 head 는 불변.

params:
    head_name: str — 대상 head 이름 (필수).
    mapping:   dict[str, str] — 원래 class 이름 → 새 class 이름 (필수, 최소 1개).
        - 원래 이름이 classes 에 없으면 무시하고 경고만.
        - 동일 new_name 으로 2개 이상 매핑되면 에러 (class 병합은 cls_merge_classes 사용).
        - rename 결과가 같은 head 의 기존 다른 class 이름과 충돌하면 에러.

주로 merge 이전에 class 이름 충돌을 회피하기 위해 사용한다.
classes 순서는 학습 output index SSOT 이므로 rename 은 순서를 보존한다.
이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)


class RenameClassClassification(UnitManipulator):
    """DB seed name: "cls_rename_class"."""

    REQUIRED_PARAMS = ["head_name", "mapping"]

    @property
    def name(self) -> str:
        return "cls_rename_class"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_rename_class 는 단일 입력만 지원합니다 (list 입력 불가)."
            )
        if input_meta.head_schema is None:
            raise ValueError(
                "cls_rename_class 는 classification DatasetMeta 에만 사용합니다 "
                "(head_schema 가 None 입니다)."
            )

        target_head_name = params.get("head_name")
        if not isinstance(target_head_name, str) or not target_head_name.strip():
            raise ValueError(
                "head_name 이 비어있습니다. 대상 Head 이름을 지정하세요."
            )
        target_head_name = target_head_name.strip()

        mapping = params.get("mapping", {})
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(
                "mapping 이 비어있습니다. 원래 Class 이름 → 새 Class 이름 매핑을 "
                "하나 이상 입력하세요."
            )

        # 동일 new_name 으로 복수 class 를 매핑하는 경우는 class 병합 시맨틱.
        # 병합은 별도 operator(cls_merge_classes) 로 처리하므로 여기서는 차단.
        inverse: dict[str, list[str]] = {}
        for original_name, new_name in mapping.items():
            inverse.setdefault(new_name, []).append(original_name)
        collapsed = {new: olds for new, olds in inverse.items() if len(olds) > 1}
        if collapsed:
            raise ValueError(
                f"cls_rename_class: 동일한 new_name 으로 매핑된 Class 이름이 "
                f"있습니다. Class 병합은 cls_merge_classes 를 사용하세요. "
                f"충돌={collapsed}"
            )

        # 대상 head 찾기.
        existing_head_names = [head.name for head in input_meta.head_schema]
        target_head: HeadSchema | None = next(
            (head for head in input_meta.head_schema if head.name == target_head_name),
            None,
        )
        if target_head is None:
            raise ValueError(
                f"cls_rename_class: head_name='{target_head_name}' 가 head_schema 에 "
                f"없습니다. 존재하는 head: {existing_head_names}"
            )

        existing_class_set = set(target_head.classes)
        unmatched_keys = set(mapping.keys()) - existing_class_set
        if unmatched_keys:
            logger.warning(
                "cls_rename_class: 매핑에 지정되었으나 head '%s' 의 classes 에 없는 "
                "이름 (무시됨): %s",
                target_head_name,
                sorted(unmatched_keys),
            )

        # rename 결과 중복 검사 (순서 보존 rename 후 set 크기 비교).
        renamed_classes = [mapping.get(cls, cls) for cls in target_head.classes]
        if len(set(renamed_classes)) != len(renamed_classes):
            duplicate_set = {
                name for name in renamed_classes if renamed_classes.count(name) > 1
            }
            raise ValueError(
                f"cls_rename_class: rename 결과 head '{target_head_name}' 의 class "
                f"이름이 중복됩니다: {sorted(duplicate_set)}. 매핑을 조정하거나 "
                f"cls_merge_classes 를 사용하세요."
            )

        # head_schema 재구성 — 대상 head 만 교체, 나머지는 얕은 복제.
        new_head_schema = [
            HeadSchema(
                name=head.name,
                multi_label=head.multi_label,
                classes=renamed_classes if head.name == target_head_name else list(head.classes),
            )
            for head in input_meta.head_schema
        ]

        # image_records labels[target_head_name] 의 class 이름 rename.
        new_records: list[ImageRecord] = []
        label_rename_count = 0
        for record in input_meta.image_records:
            source_labels = record.labels or {}
            head_label_value = source_labels.get(target_head_name)
            if head_label_value is not None and target_head_name in source_labels:
                # known labels — class 이름 rename 수행.
                new_class_names: list[str] = []
                for class_name in head_label_value:
                    renamed = mapping.get(class_name, class_name)
                    if renamed != class_name:
                        label_rename_count += 1
                    new_class_names.append(renamed)
                new_labels: dict[str, list[str] | None] = {
                    head_name: (
                        new_class_names
                        if head_name == target_head_name
                        else (list(class_names) if class_names is not None else None)
                    )
                    for head_name, class_names in source_labels.items()
                }
            else:
                # 대상 head 가 없거나 None(unknown) — labels 를 얕게 복제만.
                new_labels = {
                    head_name: (list(class_names) if class_names is not None else None)
                    for head_name, class_names in source_labels.items()
                }
            new_records.append(
                replace(
                    record,
                    labels=new_labels,
                    extra=dict(record.extra) if record.extra else {},
                )
            )

        class_rename_count = sum(
            1
            for original_name, new_name in zip(target_head.classes, renamed_classes, strict=True)
            if original_name != new_name
        )
        logger.info(
            "cls_rename_class 완료: head='%s' class %d개 중 %d개 rename, "
            "labels 값 %d건 rename",
            target_head_name,
            len(target_head.classes),
            class_rename_count,
            label_rename_count,
        )

        return DatasetMeta(
            dataset_id=input_meta.dataset_id,
            storage_uri=input_meta.storage_uri,
            categories=[],
            image_records=new_records,
            head_schema=new_head_schema,
            extra=dict(input_meta.extra) if input_meta.extra else {},
        )
