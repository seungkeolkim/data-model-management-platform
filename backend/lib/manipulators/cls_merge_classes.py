"""
cls_merge_classes — 같은 Head 내 여러 Class 를 하나로 통합하는 manipulator.

역할:
    지정 head 의 여러 source class 를 하나의 target class 로 병합한다.
    예: head="vehicle", source_classes=["sedan", "suv", "van"], target_class="car"

    head_schema 변경:
      - source_classes 를 classes 에서 제거하고, target_class 를 첫 번째
        source_class 가 있던 위치에 삽입한다.
      - target_class 가 source_classes 중 하나이면 해당 위치에 유지, 나머지만 제거.

    labels 변경:
      - null(unknown) → null 유지.
      - single-label head: labels[head] 가 source_classes 중 하나이면 [target_class] 로 교체.
        그 외 값이면 그대로 유지.
      - multi-label head: labels[head] 리스트에 source_classes 중 하나라도 있으면
        해당 항목들을 제거하고 target_class 를 추가 (OR 병합). 없으면 그대로 유지.

params:
    head_name:      str       — 대상 head 이름 (필수).
    source_classes: list[str] — 병합 대상 class 이름 목록 (필수, 최소 2개).
    target_class:   str       — 병합 후 class 이름 (필수). source_classes 중 하나이거나 신규 이름.

이미지 바이너리 불변 → file_name 유지 → lazy copy.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)


class MergeClassesClassification(UnitManipulator):
    """DB seed name: "cls_merge_classes"."""

    REQUIRED_PARAMS = ["head_name", "source_classes", "target_class"]

    @property
    def name(self) -> str:
        return "cls_merge_classes"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_merge_classes 는 단일 입력만 지원합니다 (list 입력 불가)."
            )
        if input_meta.head_schema is None:
            raise ValueError(
                "cls_merge_classes 는 classification DatasetMeta 에만 사용합니다 "
                "(head_schema 가 None 입니다)."
            )

        target_head_name = params.get("head_name")
        if not isinstance(target_head_name, str) or not target_head_name.strip():
            raise ValueError(
                "head_name 이 비어있습니다. 대상 Head 이름을 지정하세요."
            )
        target_head_name = target_head_name.strip()

        source_classes = self._parse_source_classes(params.get("source_classes"))
        if len(set(source_classes)) != len(source_classes):
            raise ValueError(
                f"source_classes 에 중복이 있습니다: {source_classes}"
            )

        target_class = params.get("target_class")
        if not isinstance(target_class, str) or not target_class.strip():
            raise ValueError(
                "target_class 가 비어있습니다. 병합 결과 class 이름을 지정하세요."
            )
        target_class = target_class.strip()

        # 대상 head 찾기.
        target_head: HeadSchema | None = next(
            (head for head in input_meta.head_schema if head.name == target_head_name),
            None,
        )
        if target_head is None:
            existing_head_names = [head.name for head in input_meta.head_schema]
            raise ValueError(
                f"cls_merge_classes: head_name='{target_head_name}' 가 head_schema 에 "
                f"없습니다. 존재하는 head: {existing_head_names}"
            )

        source_class_set = set(source_classes)
        existing_class_set = set(target_head.classes)

        # source_classes 가 실제 classes 에 있는지 검증.
        missing_source = source_class_set - existing_class_set
        if missing_source:
            raise ValueError(
                f"cls_merge_classes: source_classes 중 head '{target_head_name}' 의 "
                f"classes 에 없는 이름이 있습니다: {sorted(missing_source)}. "
                f"존재하는 classes: {target_head.classes}"
            )

        # target_class 가 source_classes 에 포함되지 않으면서 이미 classes 에 있으면
        # 병합 결과 중복이 생기므로 에러.
        if target_class not in source_class_set and target_class in existing_class_set:
            raise ValueError(
                f"cls_merge_classes: target_class='{target_class}' 가 이미 head "
                f"'{target_head_name}' 의 classes 에 존재하지만 source_classes 에는 "
                f"포함되지 않아 중복이 발생합니다. target_class 를 source_classes 중 "
                f"하나로 지정하거나 새 이름을 사용하세요."
            )

        # ── head_schema 재구성 ──
        # source_classes 의 첫 등장 위치에 target_class 를 놓고, 나머지 source 를 제거.
        new_classes = _build_merged_classes(
            original_classes=target_head.classes,
            source_class_set=source_class_set,
            target_class=target_class,
        )

        new_head_schema = [
            HeadSchema(
                name=head.name,
                multi_label=head.multi_label,
                classes=new_classes if head.name == target_head_name else list(head.classes),
            )
            for head in input_meta.head_schema
        ]

        # ── image_records labels 변환 ──
        is_multi_label = target_head.multi_label
        new_records: list[ImageRecord] = []
        merge_count = 0

        for record in input_meta.image_records:
            source_labels = record.labels or {}
            head_label_value = source_labels.get(target_head_name)

            if head_label_value is None or target_head_name not in source_labels:
                # unknown 또는 해당 head 자체가 없음 — 그대로 복제.
                new_labels = _shallow_copy_labels(source_labels)
            elif is_multi_label:
                merged_value, did_merge = _merge_multi_label(
                    head_label_value, source_class_set, target_class,
                )
                if did_merge:
                    merge_count += 1
                new_labels = {
                    head_name: (
                        merged_value
                        if head_name == target_head_name
                        else (list(class_names) if class_names is not None else None)
                    )
                    for head_name, class_names in source_labels.items()
                }
            else:
                merged_value, did_merge = _merge_single_label(
                    head_label_value, source_class_set, target_class,
                )
                if did_merge:
                    merge_count += 1
                new_labels = {
                    head_name: (
                        merged_value
                        if head_name == target_head_name
                        else (list(class_names) if class_names is not None else None)
                    )
                    for head_name, class_names in source_labels.items()
                }

            new_records.append(
                replace(
                    record,
                    labels=new_labels,
                    extra=dict(record.extra) if record.extra else {},
                )
            )

        logger.info(
            "cls_merge_classes 완료: head='%s', %s → '%s', "
            "classes %d→%d개, labels %d건 병합",
            target_head_name,
            source_classes,
            target_class,
            len(target_head.classes),
            len(new_classes),
            merge_count,
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
    def _parse_source_classes(raw_value: Any) -> list[str]:
        """params.source_classes 를 list/str/None → list[str] 정규화.

        DynamicParamForm 의 textarea 타입은 줄바꿈 구분 문자열을 보낸다.
        list 도 수용한다 (API 직접 호출 대비).
        """
        if raw_value is None:
            raise ValueError(
                "source_classes 는 필수입니다. 병합 대상 class 이름 2개 이상을 입력하세요."
            )
        if isinstance(raw_value, str):
            names = [line.strip() for line in raw_value.splitlines() if line.strip()]
        elif isinstance(raw_value, (list, tuple)):
            names = [str(item).strip() for item in raw_value if str(item).strip()]
        else:
            raise ValueError(
                f"source_classes 는 list 또는 str 이어야 합니다: {type(raw_value).__name__}"
            )
        if len(names) < 2:
            raise ValueError(
                "source_classes 는 병합 대상 class 이름 2개 이상이어야 합니다. "
                f"got: {names!r}"
            )
        if len(set(names)) != len(names):
            raise ValueError(f"source_classes 에 중복이 있습니다: {names}")
        return names


# ─────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────


def _build_merged_classes(
    original_classes: list[str],
    source_class_set: set[str],
    target_class: str,
) -> list[str]:
    """source_classes 를 제거하고 첫 번째 source 위치에 target_class 를 삽입한 classes 배열 반환."""
    result: list[str] = []
    target_inserted = False
    for cls_name in original_classes:
        if cls_name in source_class_set:
            if not target_inserted:
                result.append(target_class)
                target_inserted = True
            # source_class_set 에 속하는 나머지 class 는 건너뜀.
        else:
            result.append(cls_name)
    return result


def _merge_single_label(
    label_value: list[str],
    source_class_set: set[str],
    target_class: str,
) -> tuple[list[str], bool]:
    """single-label head: source_classes 중 하나면 target_class 로 교체.

    Returns:
        (new_label_value, did_merge)
    """
    # single-label 이므로 len(label_value) == 1 이어야 함 (writer assert 가 보장).
    if label_value and label_value[0] in source_class_set:
        return [target_class], True
    return list(label_value), False


def _merge_multi_label(
    label_value: list[str],
    source_class_set: set[str],
    target_class: str,
) -> tuple[list[str], bool]:
    """multi-label head: source_classes 중 하나라도 있으면 OR 병합.

    source_classes 에 해당하는 항목을 모두 제거하고 target_class 를 추가한다.
    이미 target_class 가 있으면 중복 추가하지 않는다.

    Returns:
        (new_label_value, did_merge)
    """
    has_source = any(cls_name in source_class_set for cls_name in label_value)
    if not has_source:
        return list(label_value), False

    # source 제거 후 target 추가.
    new_value = [cls_name for cls_name in label_value if cls_name not in source_class_set]
    if target_class not in new_value:
        new_value.append(target_class)
    return new_value, True


def _shallow_copy_labels(
    source_labels: dict[str, list[str] | None],
) -> dict[str, list[str] | None]:
    """labels dict 의 얕은 복제. None(unknown) 보존."""
    return {
        head_name: (list(class_names) if class_names is not None else None)
        for head_name, class_names in source_labels.items()
    }
