"""
cls_rename_head — Classification 전용 Head 이름 변경 manipulator.

역할:
    head_schema[*].name 을 매핑에 따라 변경하고, image_records[*].labels 의
    키(= head 이름) 도 동일한 매핑으로 rename 한다. classes 배열과
    multi_label 플래그는 건드리지 않는다.

주요 용도:
    merge 이전에 서로 다른 원천의 head 이름이 충돌하는 경우(서로 다른 의미의
    동명 head, 또는 같은 의미의 다른 이름) 를 정리한다.

params:
    mapping: dict[str, str] — 원래 head 이름 → 새 head 이름 (필수, 최소 1개).
        - 원래 이름이 head_schema 에 없으면 무시하고 경고만 남긴다.
        - rename 결과가 기존의 다른 head 이름과 충돌하면 에러.
        - 같은 new_name 으로 2개 이상 이름이 매핑되면 에러
          (head 병합은 의미가 모호하므로 지원하지 않음).

이미지 바이너리는 불변 → sha/file_name 유지 → lazy copy.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)


class RenameHeadClassification(UnitManipulator):
    """DB seed name: "cls_rename_head"."""

    REQUIRED_PARAMS = ["mapping"]

    @property
    def name(self) -> str:
        return "cls_rename_head"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_rename_head 는 단일 입력만 지원합니다 (list 입력 불가)."
            )
        if input_meta.head_schema is None:
            raise ValueError(
                "cls_rename_head 는 classification DatasetMeta 에만 사용합니다 "
                "(head_schema 가 None 입니다)."
            )

        mapping = params.get("mapping", {})
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(
                "mapping 이 비어있습니다. 원래 Head 이름 → 새 Head 이름 매핑을 "
                "하나 이상 입력하세요."
            )

        # 동일 new_name 으로 복수 이름이 매핑되는 경우는 head 병합을 의미하는데,
        # labels(dict) 구조상 병합 시맨틱이 모호하므로 차단한다.
        inverse: dict[str, list[str]] = {}
        for original_name, new_name in mapping.items():
            inverse.setdefault(new_name, []).append(original_name)
        collapsed = {new: olds for new, olds in inverse.items() if len(olds) > 1}
        if collapsed:
            raise ValueError(
                f"cls_rename_head: 동일한 new_name 으로 매핑된 Head 이름이 있습니다. "
                f"Head 병합은 지원하지 않습니다. 충돌={collapsed}"
            )

        existing_head_names = [head.name for head in input_meta.head_schema]
        existing_name_set = set(existing_head_names)

        unmatched_keys = set(mapping.keys()) - existing_name_set
        if unmatched_keys:
            logger.warning(
                "cls_rename_head: 매핑에 지정되었으나 head_schema 에 없는 이름 (무시됨): %s",
                sorted(unmatched_keys),
            )

        # rename 결과가 다른 head 이름과 충돌하는지 검사.
        # 충돌 조건: 새 이름이 (변경 대상이 아닌) 기존 head 이름과 같은 경우.
        # 또한 rename 후 동일 이름 중복 검사.
        renamed_names: list[str] = []
        for head in input_meta.head_schema:
            new_name = mapping.get(head.name, head.name)
            renamed_names.append(new_name)

        if len(set(renamed_names)) != len(renamed_names):
            duplicate_set = {
                name for name in renamed_names if renamed_names.count(name) > 1
            }
            raise ValueError(
                f"cls_rename_head: rename 결과 Head 이름이 중복됩니다: "
                f"{sorted(duplicate_set)}. 매핑을 조정해주세요."
            )

        # head_schema 재구성 (순서 보존, classes/multi_label 그대로).
        new_head_schema = [
            HeadSchema(
                name=mapping.get(head.name, head.name),
                multi_label=head.multi_label,
                classes=list(head.classes),
            )
            for head in input_meta.head_schema
        ]

        # image_records 의 labels 키 rename.
        new_records: list[ImageRecord] = []
        rename_count = 0
        for record in input_meta.image_records:
            new_labels: dict[str, list[str]] = {}
            for head_name, class_names in (record.labels or {}).items():
                renamed = mapping.get(head_name, head_name)
                if renamed != head_name:
                    rename_count += 1
                new_labels[renamed] = list(class_names)
            new_records.append(
                replace(
                    record,
                    labels=new_labels,
                    extra=dict(record.extra) if record.extra else {},
                )
            )

        head_rename_count = sum(
            1
            for original_name, new_name in zip(existing_head_names, renamed_names, strict=True)
            if original_name != new_name
        )
        logger.info(
            "cls_rename_head 완료: head %d개 중 %d개 rename, labels 키 %d건 rename",
            len(input_meta.head_schema),
            head_rename_count,
            rename_count,
        )

        return DatasetMeta(
            dataset_id=input_meta.dataset_id,
            storage_uri=input_meta.storage_uri,
            categories=[],
            image_records=new_records,
            head_schema=new_head_schema,
            extra=dict(input_meta.extra) if input_meta.extra else {},
        )
