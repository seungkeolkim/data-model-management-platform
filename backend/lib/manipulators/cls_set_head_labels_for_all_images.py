"""
cls_set_head_labels_for_all_images — 특정 Head 의 labels 를 모든 이미지에서 일괄 덮어쓰기.

역할:
    지정한 head 의 labels 를 전체 이미지에서 동일 값으로 overwrite. 주요 용도:
      1. head 전체를 unknown(null) 으로 되돌리기 (set_unknown=True).
      2. 특정 class 조합으로 일괄 지정 (set_unknown=False + classes).

    head_schema / file_name 은 변경하지 않는다 (labels 만 교체). 이미지 바이너리 불변 →
    Phase B 는 lazy copy.

params:
    head_name:   text      — 대상 head 이름 (필수, 기존 head_schema 에 존재해야 함).
    set_unknown: checkbox  — 체크 시 모든 이미지의 해당 head labels 를 null 로 교체.
                              기본 False.
    classes:     textarea  — set_unknown=False 일 때 사용. 줄바꿈 구분.
                              - single-label head: 정확히 1개 (0 개 또는 2개 이상 → ValueError).
                              - multi-label head: 0개 이상 (빈 리스트 = explicit empty = §2-12).
                              - 모든 class 이름은 대상 head 의 classes 에 포함되어야 함.

설계 결정:
    - set_unknown 과 classes 는 상호배타. set_unknown=True 면 classes 는 무시된다
      (사용자가 실수로 둘 다 채워도 unknown 이 우선).
    - single-label head 에 다수 class 를 set 하려고 하면 ValueError 로 즉시 차단.
      writer 단계까지 가서 assert 로 떨어지지 않도록 미리 막는다 (§2-12).
    - 존재하지 않는 class 이름을 입력하면 ValueError — head_schema.classes 는 SSOT 이므로
      새 class 가 필요하면 cls_rename_class / cls_add_head 등을 먼저 써야 한다.

head_schema / file_name 변경 없음 (labels 만 overwrite) → lazy copy.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)


# =============================================================================
# 순수 params 검증 — runtime (transform_annotation) 과 정적 DB-aware 검증
# (PipelineService) 양쪽에서 동일 규칙을 공유하도록 모듈 레벨로 노출.
#
# 반환 형식: (issue_code, human_readable_message) 튜플의 리스트.
#   - runtime 은 첫 원소만 쓰고 ValueError 로 올린다 (transform_annotation).
#   - 정적 검증은 리스트 전체를 PipelineValidationIssue 로 변환한다.
# =============================================================================


def validate_set_head_labels_params(
    head_schema: list[HeadSchema] | None,
    params: dict[str, Any],
) -> list[tuple[str, str]]:
    """
    cls_set_head_labels_for_all_images params 를 head_schema 와 대조해 위반 목록을 반환.

    head_schema 가 None 이면 `HEAD_SCHEMA_MISSING` 한 건만 반환하고 이후 검증은 skip.
    그 외에는 다음 규칙을 순차 평가하되, 먼저 파싱 오류가 나면 그 한 건만 반환한다
    (후속 검증이 의미를 잃기 때문).

    규칙:
      HEAD_NAME_MISSING       — head_name 누락/공백
      HEAD_NAME_NOT_FOUND     — head_name 이 head_schema 에 없음
      CLASSES_DUPLICATE       — classes 에 중복된 class 이름
      CLASSES_NOT_IN_SCHEMA   — classes 에 head_schema 바깥 class 이름 (SSOT 위반)
      SINGLE_LABEL_ARITY      — single-label head 에 0개 또는 2개 이상 classes
    """
    if head_schema is None:
        return [(
            "HEAD_SCHEMA_MISSING",
            "cls_set_head_labels_for_all_images 는 classification 데이터셋 "
            "(head_schema 보유) 에만 사용할 수 있습니다.",
        )]

    # head_name 파싱 — 실패하면 단건만 반환.
    try:
        target_head_name = _parse_head_name(params.get("head_name"))
    except ValueError as error:
        return [("HEAD_NAME_MISSING", str(error))]

    # head 존재 여부.
    target_head: HeadSchema | None = None
    for head in head_schema:
        if head.name == target_head_name:
            target_head = head
            break
    if target_head is None:
        existing = [head.name for head in head_schema]
        return [(
            "HEAD_NAME_NOT_FOUND",
            f"head_name='{target_head_name}' 을 head_schema 에서 찾지 못했습니다. "
            f"존재하는 head: {existing}",
        )]

    # set_unknown=True 면 classes 검증 스킵.
    try:
        set_unknown = _parse_set_unknown(params.get("set_unknown", False))
    except ValueError as error:
        return [("SET_UNKNOWN_INVALID", str(error))]
    if set_unknown:
        return []

    # classes 파싱.
    try:
        class_names = _parse_classes(params.get("classes"))
    except ValueError as error:
        return [("CLASSES_INVALID", str(error))]

    issues: list[tuple[str, str]] = []

    # 중복.
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in class_names:
        if name in seen:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        issues.append((
            "CLASSES_DUPLICATE",
            f"classes 에 중복된 class 이름이 있습니다: {duplicates}",
        ))

    # SSOT 위반.
    allowed = set(target_head.classes)
    unknown = [name for name in class_names if name not in allowed]
    if unknown:
        issues.append((
            "CLASSES_NOT_IN_SCHEMA",
            f"classes 에 head_schema 에 없는 class 가 포함되어 있습니다: "
            f"{unknown} (허용: {target_head.classes})",
        ))

    # single-label arity.
    if not target_head.multi_label and len(class_names) != 1:
        issues.append((
            "SINGLE_LABEL_ARITY",
            f"single-label head '{target_head.name}' 에는 정확히 1개의 class 만 "
            f"set 할 수 있습니다. 입력 개수: {len(class_names)} ({class_names}). "
            f"0개로 비우려면 set_unknown=True 를 사용하세요.",
        ))

    return issues


# =============================================================================
# 내부 파싱 헬퍼 (검증 함수 + manipulator 양쪽에서 재사용)
# =============================================================================


def _parse_head_name(raw_value: Any) -> str:
    """head_name 을 str 로 정규화. 비어있으면 ValueError."""
    if raw_value is None:
        raise ValueError("head_name 은 필수 입력입니다.")
    if not isinstance(raw_value, str):
        raise ValueError(
            f"head_name 은 문자열이어야 합니다: {type(raw_value).__name__}"
        )
    stripped = raw_value.strip()
    if not stripped:
        raise ValueError("head_name 이 공백입니다. 대상 Head 이름을 지정하세요.")
    return stripped


def _parse_set_unknown(raw_value: Any) -> bool:
    """set_unknown checkbox 값을 bool 로 정규화. 기본 False."""
    if isinstance(raw_value, bool):
        return raw_value
    if raw_value is None:
        return False
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in ("true", "1", "yes", "on"):
            return True
        if normalized in ("false", "0", "no", "off", ""):
            return False
        raise ValueError(
            f"set_unknown 문자열 값은 true/false 계열이어야 합니다: {raw_value!r}"
        )
    raise ValueError(
        f"set_unknown 은 bool 이어야 합니다: {type(raw_value).__name__}"
    )


def _parse_classes(raw_value: Any) -> list[str]:
    """
    classes 를 list[str] 로 정규화. 비어있어도 허용 — single-label 여부는
    상위에서 별도 검증한다.

    허용 입력:
        - None / "" → 빈 리스트.
        - str (textarea): 줄바꿈 구분, trim 후 빈 줄 제외.
        - list[str] / tuple[str]: 각 원소 trim 후 빈 값 제외.
    """
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        return [line.strip() for line in raw_value.splitlines() if line.strip()]
    if isinstance(raw_value, (list, tuple)):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    raise ValueError(
        f"classes 는 str 또는 list 이어야 합니다: {type(raw_value).__name__}"
    )


class SetHeadLabelsForAllImagesClassification(UnitManipulator):
    """DB seed name: "cls_set_head_labels_for_all_images"."""

    REQUIRED_PARAMS = ["head_name"]

    @property
    def name(self) -> str:
        return "cls_set_head_labels_for_all_images"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_set_head_labels_for_all_images 는 단건 DatasetMeta 만 입력 가능합니다 "
                "(list 입력 불가)."
            )

        # ── params + head_schema 공통 검증 (정적 검증과 규칙 공유) ──
        issues = validate_set_head_labels_params(input_meta.head_schema, params)
        if issues:
            _, first_message = issues[0]
            raise ValueError(first_message)

        # 검증 통과 → 파싱된 값을 사용 (input_meta.head_schema 는 여기서 None 이 아님이
        # 보장된다 — HEAD_SCHEMA_MISSING 이 issues 로 잡혔을 것).
        assert input_meta.head_schema is not None
        target_head_name = _parse_head_name(params.get("head_name"))
        set_unknown = _parse_set_unknown(params.get("set_unknown", False))

        # ── 교체할 labels 값 결정 ──
        if set_unknown:
            replacement: list[str] | None = None
        else:
            class_names = _parse_classes(params.get("classes"))
            replacement = list(class_names)

        # ── head_schema 는 그대로 복사 (불변) ──
        new_head_schema = [
            HeadSchema(
                name=head.name,
                multi_label=head.multi_label,
                classes=list(head.classes),
            )
            for head in input_meta.head_schema
        ]

        # ── 모든 이미지의 target head labels 를 일괄 교체 ──
        new_records: list[ImageRecord] = []
        for record in input_meta.image_records:
            source_labels = record.labels or {}
            new_labels: dict[str, list[str] | None] = {
                head_name: (list(class_names) if class_names is not None else None)
                for head_name, class_names in source_labels.items()
            }
            # 원본에 target_head 가 없어도(신규 head 직후 등) 이번 단계에서 채워진다.
            new_labels[target_head_name] = (
                None if replacement is None else list(replacement)
            )
            new_records.append(
                replace(
                    record,
                    labels=new_labels,
                    extra=dict(record.extra) if record.extra else {},
                )
            )

        logger.info(
            "cls_set_head_labels_for_all_images 완료: head='%s', set_unknown=%s, "
            "replacement=%s, 적용 이미지 %d장",
            target_head_name,
            set_unknown,
            "null" if replacement is None else replacement,
            len(new_records),
        )

        return DatasetMeta(
            dataset_id=input_meta.dataset_id,
            storage_uri=input_meta.storage_uri,
            categories=[],
            image_records=new_records,
            head_schema=new_head_schema,
            extra=dict(input_meta.extra) if input_meta.extra else {},
        )
