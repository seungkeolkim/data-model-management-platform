"""
cls_merge_datasets 입력 호환성 검증.

Classification merge 정책 (`objective_n_plan_7th.md §2-11`) 의 정적 검증 로직을
하나로 모아 둔다. 두 호출자가 동일한 규칙을 공유한다:

  1. `cls_merge_datasets` manipulator — 실행 시점에 입력 DatasetMeta 들을 받아
     호환성 문제가 있으면 ValueError 로 실패 (API 우회 방어).
  2. `PipelineService._validate_with_database` — 실행 전 DB 검증 단계에서
     preview_head_schema_at_task 로 각 입력의 head_schema 를 계산한 뒤 이 함수를
     호출해 `PipelineValidationIssue` 로 변환 → FE 가 Merge 노드에 이슈로 표시.

lib/ 레이어이므로 DB/FastAPI 의존성 없음. `MergeCompatibilityIssue` 는 호출자가
자유로운 형식(ValueError, PipelineValidationIssue 등) 으로 변환한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lib.pipeline.pipeline_data_models import HeadSchema

# =============================================================================
# 옵션 값 상수
# =============================================================================

OPTION_ON_HEAD_MISMATCH = "on_head_mismatch"
OPTION_ON_CLASS_SET_MISMATCH = "on_class_set_mismatch"

HEAD_MISMATCH_ERROR = "error"
HEAD_MISMATCH_FILL_EMPTY = "fill_empty"
HEAD_MISMATCH_ALLOWED = {HEAD_MISMATCH_ERROR, HEAD_MISMATCH_FILL_EMPTY}

CLASS_SET_MISMATCH_ERROR = "error"
CLASS_SET_MISMATCH_MULTI_LABEL_UNION = "multi_label_union"
CLASS_SET_MISMATCH_ALLOWED = {CLASS_SET_MISMATCH_ERROR, CLASS_SET_MISMATCH_MULTI_LABEL_UNION}


def resolve_merge_params(params: dict[str, Any] | None) -> dict[str, str]:
    """
    params dict 에서 merge 2옵션의 최종 값을 뽑는다. 미지정이면 default,
    허용값 외의 값이면 ValueError.

    과거에 존재하던 `on_label_conflict` 옵션은 filename identity 확정(§2-8)으로
    SHA 기반 content dedup 이 폐지되면서 함께 제거됐다. 같은 파일명이 여러 입력에
    걸쳐도 rename 으로 공존시키므로 label 충돌 판정 자체가 필요 없어졌다.

    Returns:
        {"on_head_mismatch": "...", "on_class_set_mismatch": "..."}
    """
    params = params or {}
    on_head = str(params.get(OPTION_ON_HEAD_MISMATCH) or HEAD_MISMATCH_ERROR)
    on_class = str(params.get(OPTION_ON_CLASS_SET_MISMATCH) or CLASS_SET_MISMATCH_ERROR)

    if on_head not in HEAD_MISMATCH_ALLOWED:
        allowed = sorted(HEAD_MISMATCH_ALLOWED)
        raise ValueError(
            f"{OPTION_ON_HEAD_MISMATCH} 값은 {allowed} 중 하나여야 합니다: {on_head!r}"
        )
    if on_class not in CLASS_SET_MISMATCH_ALLOWED:
        allowed = sorted(CLASS_SET_MISMATCH_ALLOWED)
        raise ValueError(
            f"{OPTION_ON_CLASS_SET_MISMATCH} 값은 {allowed} 중 하나여야 합니다: {on_class!r}"
        )
    return {
        OPTION_ON_HEAD_MISMATCH: on_head,
        OPTION_ON_CLASS_SET_MISMATCH: on_class,
    }


# =============================================================================
# 호환성 이슈 표현
# =============================================================================


@dataclass
class MergeCompatibilityIssue:
    """
    입력 head_schema 들을 비교한 결과 하나.

    - `code`: 기계 판독용 이슈 코드 (예: "HEAD_SET_MISMATCH")
    - `message`: 사람이 읽을 한글 메시지. "어느 manipulator 로 선행 정리하라" 포함.
    - `field_suffix`: 이슈가 관련된 필드 경로의 suffix ("inputs" | "inputs.<head_name>" 등).
        호출자가 `tasks.<task_name>.` 을 prefix 로 붙여 최종 field 경로를 구성한다.
    """

    code: str
    message: str
    field_suffix: str = "inputs"


# =============================================================================
# 호환성 검증 본체
# =============================================================================


def check_merge_schema_compatibility(
    head_schemas: list[list[HeadSchema] | None],
    params: dict[str, Any] | None,
) -> list[MergeCompatibilityIssue]:
    """
    N 개 입력의 head_schema 를 비교해 §2-11-2 표의 9개 충돌을 검사한다.

    Args:
        head_schemas: 입력 개수만큼의 head_schema 리스트. classification 파이프라인에서만
            사용되므로 각 원소는 None 이 아닌 `list[HeadSchema]` 가 정상. None 이 들어오면
            TASK_KIND_MISMATCH 이슈로 보고 (정적 검증 시점에 head_schema 가 아직 없을 수 있음).
        params: cls_merge_datasets 의 params. `on_head_mismatch` / `on_class_set_mismatch` 값에
            따라 일부 불일치를 통과시킬지 결정.

    Returns:
        이슈 리스트. 비어 있으면 호환 OK. 호출자는 이 결과를 manipulator 진입 시 ValueError 로
        바꾸거나, validator 에서 PipelineValidationIssue 로 변환해 사용한다.
    """
    issues: list[MergeCompatibilityIssue] = []

    if len(head_schemas) < 2:
        issues.append(
            MergeCompatibilityIssue(
                code="MERGE_MIN_INPUTS",
                message="cls_merge_datasets 는 최소 2개 이상의 입력이 필요합니다.",
            )
        )
        return issues

    # 입력별 head_schema 유효성: None 이면 classification 파이프라인이 아님.
    for input_index, schema in enumerate(head_schemas):
        if schema is None:
            issues.append(
                MergeCompatibilityIssue(
                    code="TASK_KIND_MISMATCH",
                    message=(
                        f"입력 #{input_index + 1} 이 classification 데이터셋이 아닙니다 "
                        f"(head_schema 가 None). cls_merge_datasets 는 classification "
                        f"데이터만 병합합니다."
                    ),
                    field_suffix=f"inputs.{input_index}",
                )
            )
    if any(schema is None for schema in head_schemas):
        # 이후 로직은 list[HeadSchema] 가정이라 조기 반환.
        return issues

    resolved = resolve_merge_params(params)
    on_head_mismatch = resolved[OPTION_ON_HEAD_MISMATCH]
    on_class_set_mismatch = resolved[OPTION_ON_CLASS_SET_MISMATCH]

    # 타입 힌트 좁히기 위한 재할당 (None 이 없음을 위 루프가 보장).
    schemas: list[list[HeadSchema]] = [schema for schema in head_schemas if schema is not None]

    # ── Head 레벨 검증 ──
    _check_head_set_and_order(schemas, on_head_mismatch, issues)
    _check_head_multi_label_flags(schemas, issues)

    # ── Class 레벨 검증 (공통 head 별) ──
    common_head_names = _intersection_preserving_first_order(schemas)
    for head_name in common_head_names:
        _check_classes_for_head(schemas, head_name, on_class_set_mismatch, issues)

    return issues


# =============================================================================
# 내부 헬퍼 — Head 레벨
# =============================================================================


def _check_head_set_and_order(
    schemas: list[list[HeadSchema]],
    on_head_mismatch: str,
    issues: list[MergeCompatibilityIssue],
) -> None:
    """
    Head 이름 집합 비교 + (집합 같을 때) 순서 비교.

    - 모든 입력의 head 집합이 disjoint (교집합 ∅) → 강제 error.
    - 교집합 존재 + 대칭차 존재 → on_head_mismatch=fill_empty 면 통과, 아니면 error.
    - 교집합 존재 + 대칭차 없음 (집합 동일) + 순서 다름 → 강제 error.
    """
    name_sets = [{head.name for head in schema} for schema in schemas]
    union_names = set().union(*name_sets)
    intersection_names = set(name_sets[0]).intersection(*name_sets[1:])

    # 모든 입력이 완전 disjoint 인 케이스: "head 이름 다름 (의미 같음)" 시나리오.
    # 옵션 허용 없이 무조건 error. (fill_empty 로 union 해도 의미 보존 불가)
    if not intersection_names and len(union_names) > 0:
        summary = "; ".join(
            f"입력 #{idx + 1}={sorted(names)}" for idx, names in enumerate(name_sets)
        )
        issues.append(
            MergeCompatibilityIssue(
                code="HEAD_NAMES_ALL_DIFFERENT",
                message=(
                    "입력들의 head 이름 집합에 공통 항목이 없습니다. "
                    "의미가 같은 head 는 cls_rename_head 로 선행 정리한 뒤 merge 하세요. "
                    f"현재 상태: {summary}"
                ),
            )
        )
        return

    # 대칭차 존재 (부분 불일치) — on_head_mismatch 옵션에 따라.
    if any(name_set != union_names for name_set in name_sets):
        only_in_each = [
            sorted(name_sets[idx] - intersection_names) for idx in range(len(name_sets))
        ]
        extra_summary = "; ".join(
            f"입력 #{idx + 1} 에만 있음={extras}"
            for idx, extras in enumerate(only_in_each)
            if extras
        )
        if on_head_mismatch == HEAD_MISMATCH_ERROR:
            issues.append(
                MergeCompatibilityIssue(
                    code="HEAD_SET_MISMATCH",
                    message=(
                        "입력들의 head 집합이 다릅니다. cls_select_heads 로 head 를 "
                        "맞추거나 on_head_mismatch=fill_empty 옵션으로 한쪽에만 있는 "
                        f"head 를 빈 라벨로 채우세요. {extra_summary}"
                    ),
                )
            )
        # fill_empty 면 통과 (정책적으로 허용된 상태).

    # 집합 동일이지만 순서 다름 — 강제 error.
    # (부분 불일치 상태에서는 intersection 기준으로 순서 검증)
    first_order = [head.name for head in schemas[0] if head.name in intersection_names]
    for schema_index, schema in enumerate(schemas[1:], start=1):
        order_in_this = [head.name for head in schema if head.name in intersection_names]
        if order_in_this != first_order:
            issues.append(
                MergeCompatibilityIssue(
                    code="HEAD_ORDER_MISMATCH",
                    message=(
                        f"공통 head 의 순서가 입력 #{schema_index + 1} 에서 다릅니다. "
                        f"입력 #1 순서={first_order}, "
                        f"입력 #{schema_index + 1} 순서={order_in_this}. "
                        "cls_reorder_heads 로 순서를 맞춘 뒤 merge 하세요."
                    ),
                    field_suffix=f"inputs.{schema_index}",
                )
            )


def _check_head_multi_label_flags(
    schemas: list[list[HeadSchema]],
    issues: list[MergeCompatibilityIssue],
) -> None:
    """동일 head 이름의 multi_label 플래그 불일치는 강제 error (의미 충돌)."""
    # head_name → 각 입력별 multi_label 값 모음
    flag_by_head: dict[str, list[tuple[int, bool]]] = {}
    for schema_index, schema in enumerate(schemas):
        for head in schema:
            flag_by_head.setdefault(head.name, []).append((schema_index, head.multi_label))

    for head_name, presence in flag_by_head.items():
        unique_flags = {flag for _, flag in presence}
        if len(unique_flags) > 1:
            per_input = ", ".join(
                f"입력 #{idx + 1}={'multi' if flag else 'single'}" for idx, flag in presence
            )
            issues.append(
                MergeCompatibilityIssue(
                    code="HEAD_MULTI_LABEL_MISMATCH",
                    message=(
                        f"head '{head_name}' 의 multi_label 플래그가 입력마다 "
                        f"다릅니다 ({per_input}). "
                        "multi_label 플래그는 사용자가 사전에 맞춰야 합니다."
                    ),
                    field_suffix=f"inputs.{head_name}",
                )
            )


# =============================================================================
# 내부 헬퍼 — Class 레벨
# =============================================================================


def _check_classes_for_head(
    schemas: list[list[HeadSchema]],
    head_name: str,
    on_class_set_mismatch: str,
    issues: list[MergeCompatibilityIssue],
) -> None:
    """
    동일 이름을 가진 head 의 classes 에 대해 head 레벨과 동일한 4단계 검증.

    - disjoint (교집합 ∅): 강제 error.
    - 대칭차 존재: on_class_set_mismatch=multi_label_union 이면 통과, 아니면 error.
    - 집합 동일, 순서 다름: 강제 error.
    """
    classes_per_input: list[tuple[int, list[str]]] = []
    for schema_index, schema in enumerate(schemas):
        for head in schema:
            if head.name == head_name:
                classes_per_input.append((schema_index, list(head.classes)))
                break

    # 해당 head 가 한 입력에만 있으면 class 검증은 불필요 (head 레벨 옵션이 처리).
    if len(classes_per_input) < 2:
        return

    class_sets = [set(classes) for _, classes in classes_per_input]
    intersection = set(class_sets[0]).intersection(*class_sets[1:])
    union = set().union(*class_sets)

    # 완전 disjoint
    if not intersection and union:
        per_input = "; ".join(
            f"입력 #{schema_index + 1}={classes}"
            for schema_index, classes in classes_per_input
        )
        issues.append(
            MergeCompatibilityIssue(
                code="CLASS_NAMES_ALL_DIFFERENT",
                message=(
                    f"head '{head_name}' 의 class 이름 집합에 공통 항목이 없습니다. "
                    "의미가 같은 class 는 cls_rename_class 로 선행 정리한 뒤 merge 하세요. "
                    f"현재 상태: {per_input}"
                ),
                field_suffix=f"inputs.{head_name}",
            )
        )
        return

    # 부분 불일치
    if any(s != union for s in class_sets):
        if on_class_set_mismatch == CLASS_SET_MISMATCH_ERROR:
            only_in_each = [
                (schema_index, sorted(class_sets[list_index] - intersection))
                for list_index, (schema_index, _) in enumerate(classes_per_input)
            ]
            extras_summary = "; ".join(
                f"입력 #{schema_index + 1} 에만 있음={extras}"
                for schema_index, extras in only_in_each
                if extras
            )
            issues.append(
                MergeCompatibilityIssue(
                    code="CLASS_SET_MISMATCH",
                    message=(
                        f"head '{head_name}' 의 class 집합이 입력마다 다릅니다. "
                        "cls_merge_classes 등으로 class 를 맞추거나, "
                        "on_class_set_mismatch=multi_label_union 옵션으로 해당 head 를 "
                        "multi_label 로 강제 승격하여 union 할 수 있습니다. "
                        f"{extras_summary}"
                    ),
                    field_suffix=f"inputs.{head_name}",
                )
            )
        # multi_label_union 이면 통과.
        return

    # 집합 동일, 순서 비교
    first_classes = classes_per_input[0][1]
    for schema_index, classes in classes_per_input[1:]:
        if classes != first_classes:
            issues.append(
                MergeCompatibilityIssue(
                    code="CLASS_ORDER_MISMATCH",
                    message=(
                        f"head '{head_name}' 의 class 순서가 "
                        f"입력 #{schema_index + 1} 에서 다릅니다. "
                        f"입력 #1 순서={first_classes}, "
                        f"입력 #{schema_index + 1} 순서={classes}. "
                        "cls_reorder_classes 로 순서를 맞춘 뒤 merge 하세요."
                    ),
                    field_suffix=f"inputs.{head_name}",
                )
            )


# =============================================================================
# 내부 헬퍼 — 공통
# =============================================================================


def _intersection_preserving_first_order(
    schemas: list[list[HeadSchema]],
) -> list[str]:
    """
    모든 입력에 공통으로 존재하는 head 이름 목록을, 첫 입력의 등장 순서 그대로 반환한다.
    class 검증이 이 순서로 수행되어 이슈 출력이 결정론적이다.
    """
    name_sets = [{head.name for head in schema} for schema in schemas]
    common = set(name_sets[0]).intersection(*name_sets[1:]) if name_sets else set()
    return [head.name for head in schemas[0] if head.name in common]
