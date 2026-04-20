"""
cls_filter_by_class — Class 기반 이미지 필터 (IMAGE_FILTER).

역할:
    지정 head 에서 class 조합과 unknown 토글을 조합한 predicate 로 이미지를 keep/drop.
    v1 은 "single-rule per node" 스타일 — 한 노드 = 하나의 (head, classes, unknown)
    조건. AND 가 필요하면 노드를 체인으로 잇고, OR 가 필요하면 branch + merge 로 푼다.

    기존 `cls_remove_images_without_label` 은 이 노드의
    `mode=exclude + classes=[] + include_unknown=True` 조합으로 완전히 대체된다 —
    Alembic 027 에서 seed 제거, 파일도 삭제.

params:
    head_name:        text      — 대상 head (head_schema 에 존재해야 함, §2-4 SSOT).
    mode:             select("include" | "exclude"), default "include".
                       - include = match=True 이미지만 keep.
                       - exclude = match=True 이미지는 drop.
    classes:          textarea  — 줄바꿈 구분, 0개 이상.
                       labels[head] 와 classes 가 교집합이 있으면 match (any policy).
                       0개면 classes 기준 match 는 항상 False → unknown 만 판정.
    include_unknown:  checkbox, default False — True 면 labels[head] == null 일 때 match.

match 규칙 (v1, any-policy 고정):
    head_labels = image.labels.get(head_name)
    if head_labels is None:          # unknown (§2-12)
        match = include_unknown
    else:                            # [] 또는 [class, ...]
        match = any(c in classes_set for c in head_labels)
    → `[]` (explicit empty) 는 unknown 이 아니라 state 가 확정된 "class 없음" 이므로,
      classes_set 과 교집합 평가 결과 False 로 흐른다 (§2-12).

    keep/drop:
      mode=include → keep if match else drop
      mode=exclude → drop if match else keep

설계 결정:
    - match_policy (any/all) 는 v1 제외. 필요 시 후속 버전에서 knob 추가.
    - classes=[] ∧ include_unknown=False 는 no-op (include 는 전부 삭제, exclude 는
      아무것도 못 함) — 둘 다 실수일 확률이 커서 ValueError 로 사전 차단.
    - 이미지 바이너리 불변 → lazy copy. record.file_name / extra 유지.

params 검증은 runtime (transform_annotation) 과 정적 (PipelineService) 양쪽에서 동일
규칙을 공유하도록 `validate_filter_by_class_params` 모듈 레벨 함수로 제공 —
`cls_set_head_labels_for_all_images` 과 동일한 패턴.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)

_VALID_MODES: set[str] = {"include", "exclude"}


# =============================================================================
# 순수 params 검증 — runtime 과 정적 DB-aware 검증 양쪽에서 공유.
# 반환 형식: (issue_code, message) 튜플 리스트.
# =============================================================================


def validate_filter_by_class_params(
    head_schema: list[HeadSchema] | None,
    params: dict[str, Any],
) -> list[tuple[str, str]]:
    """
    cls_filter_by_class params 를 head_schema 와 대조해 위반 목록을 반환.

    head_schema 가 None 이면 HEAD_SCHEMA_MISSING 한 건만 반환. 그 외에는 파싱 오류가
    먼저 나면 그 한 건만 반환하고 후속 검증은 skip.

    규칙:
      HEAD_SCHEMA_MISSING      — head_schema=None (classification 데이터셋 아님)
      HEAD_NAME_MISSING        — head_name 누락/공백
      HEAD_NAME_NOT_FOUND      — head_name 이 head_schema 에 없음
      MODE_INVALID             — mode 가 include/exclude 밖
      CLASSES_INVALID          — classes 파싱 실패
      CLASSES_DUPLICATE        — classes 에 중복된 class 이름
      CLASSES_NOT_IN_SCHEMA    — classes 에 head.classes 바깥 class 이름 (SSOT)
      INCLUDE_UNKNOWN_INVALID  — include_unknown 파싱 실패
      FILTER_MATCHES_NOTHING   — classes=[] ∧ include_unknown=False (no-op 차단)
    """
    if head_schema is None:
        return [(
            "HEAD_SCHEMA_MISSING",
            "cls_filter_by_class 는 classification 데이터셋 (head_schema 보유) 에만 "
            "사용할 수 있습니다.",
        )]

    # head_name 파싱.
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

    # mode 파싱.
    try:
        mode = _parse_mode(params.get("mode", "include"))
    except ValueError as error:
        return [("MODE_INVALID", str(error))]

    # classes 파싱.
    try:
        class_names = _parse_classes(params.get("classes"))
    except ValueError as error:
        return [("CLASSES_INVALID", str(error))]

    # include_unknown 파싱.
    try:
        include_unknown = _parse_include_unknown(params.get("include_unknown", False))
    except ValueError as error:
        return [("INCLUDE_UNKNOWN_INVALID", str(error))]

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
    unknown_classes = [name for name in class_names if name not in allowed]
    if unknown_classes:
        issues.append((
            "CLASSES_NOT_IN_SCHEMA",
            f"classes 에 head_schema 에 없는 class 가 포함되어 있습니다: "
            f"{unknown_classes} (허용: {target_head.classes})",
        ))

    # no-op 차단: classes=[] ∧ include_unknown=False.
    if not class_names and not include_unknown:
        issues.append((
            "FILTER_MATCHES_NOTHING",
            "classes 가 비어 있고 include_unknown 도 꺼져 있어 매칭되는 이미지가 "
            "없습니다 — include 는 전부 drop, exclude 는 no-op 가 되어 실수일 확률이 "
            f"높습니다. classes 를 지정하거나 include_unknown 을 켜세요. "
            f"(mode={mode})",
        ))

    return issues


# =============================================================================
# 내부 파싱 헬퍼
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


def _parse_mode(raw_value: Any) -> str:
    """mode 를 'include' | 'exclude' 로 정규화."""
    if raw_value is None:
        return "include"
    if not isinstance(raw_value, str):
        raise ValueError(
            f"mode 는 문자열이어야 합니다: {type(raw_value).__name__}"
        )
    stripped = raw_value.strip().lower()
    if stripped in _VALID_MODES:
        return stripped
    raise ValueError(
        f"mode 는 {sorted(_VALID_MODES)} 중 하나여야 합니다. 입력값: {raw_value!r}"
    )


def _parse_classes(raw_value: Any) -> list[str]:
    """
    classes 를 list[str] 로 정규화. 비어있어도 허용.

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


def _parse_include_unknown(raw_value: Any) -> bool:
    """include_unknown checkbox 값을 bool 로 정규화. 기본 False."""
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
            f"include_unknown 문자열 값은 true/false 계열이어야 합니다: {raw_value!r}"
        )
    raise ValueError(
        f"include_unknown 은 bool 이어야 합니다: {type(raw_value).__name__}"
    )


# =============================================================================
# Match 평가
# =============================================================================


def _record_matches(
    record: ImageRecord,
    head_name: str,
    classes_set: set[str],
    include_unknown: bool,
) -> bool:
    """§2-12 규약에 따른 매칭 함수 — any-policy 고정."""
    labels = record.labels or {}
    head_labels = labels.get(head_name)

    if head_labels is None:
        # null = unknown.
        return include_unknown

    # [] 또는 [class, ...] — any 교집합.
    return any(class_name in classes_set for class_name in head_labels)


class FilterByClassClassification(UnitManipulator):
    """DB seed name: "cls_filter_by_class"."""

    REQUIRED_PARAMS = ["head_name", "mode"]

    @property
    def name(self) -> str:
        return "cls_filter_by_class"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        predicate 에 따라 image_records 를 keep/drop 한 새 DatasetMeta 반환.

        Args:
            input_meta: 단건 DatasetMeta (list 는 허용하지 않음).
            params:
                - head_name:       str (필수).
                - mode:            "include" | "exclude" (기본 "include").
                - classes:         list[str] | textarea 문자열 (기본 []).
                - include_unknown: bool (기본 False).
            context: 실행 컨텍스트 (현재 사용 안 함).

        Returns:
            image_records 가 필터링된 DatasetMeta. head_schema / categories /
            storage_uri / extra 는 그대로 복사.

        Raises:
            TypeError: input_meta 가 list 인 경우.
            ValueError: params 가 `validate_filter_by_class_params` 규칙 위반.
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_filter_by_class 는 단건 DatasetMeta 만 입력 가능합니다 (list 입력 불가)."
            )

        # ── params + head_schema 공통 검증 (정적 검증과 규칙 공유) ──
        issues = validate_filter_by_class_params(input_meta.head_schema, params)
        if issues:
            _, first_message = issues[0]
            raise ValueError(first_message)

        assert input_meta.head_schema is not None  # HEAD_SCHEMA_MISSING 선검증 통과

        head_name = _parse_head_name(params.get("head_name"))
        mode = _parse_mode(params.get("mode", "include"))
        class_names = _parse_classes(params.get("classes"))
        include_unknown = _parse_include_unknown(params.get("include_unknown", False))
        classes_set = set(class_names)

        # ── head_schema 는 그대로 deep copy (불변) ──
        new_head_schema = [
            HeadSchema(
                name=head.name,
                multi_label=head.multi_label,
                classes=list(head.classes),
            )
            for head in input_meta.head_schema
        ]

        # ── image_records 필터링 ──
        kept: list[ImageRecord] = []
        drop_count = 0
        for record in input_meta.image_records:
            matched = _record_matches(record, head_name, classes_set, include_unknown)
            keep = matched if mode == "include" else not matched
            if keep:
                # lazy copy — record 자체 복제 (extra/labels 얕은 복사로 외부 변이 차단).
                kept.append(
                    replace(
                        record,
                        labels=dict(record.labels) if record.labels else {},
                        extra=dict(record.extra) if record.extra else {},
                    )
                )
            else:
                drop_count += 1

        if not kept:
            logger.warning(
                "cls_filter_by_class 결과 이미지 0장: head='%s' mode=%s classes=%s "
                "include_unknown=%s — 의도된 설정인지 확인 필요.",
                head_name, mode, class_names, include_unknown,
            )

        logger.info(
            "cls_filter_by_class 완료: head='%s' mode=%s classes=%s include_unknown=%s "
            "→ keep %d / drop %d",
            head_name, mode, class_names, include_unknown, len(kept), drop_count,
        )

        return DatasetMeta(
            dataset_id=input_meta.dataset_id,
            storage_uri=input_meta.storage_uri,
            categories=list(input_meta.categories) if input_meta.categories else [],
            image_records=kept,
            head_schema=new_head_schema,
            extra=dict(input_meta.extra) if input_meta.extra else {},
        )
