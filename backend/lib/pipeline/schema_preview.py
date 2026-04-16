"""
파이프라인 schema 프리뷰 — 실행 없이 DAG 의 특정 노드 시점에서
head_schema 가 어떻게 변할지를 계산한다.

핵심 아이디어:
    dag_executor 와 동일하게 topological order 로 각 task 의
    manipulator.transform_annotation(meta, params) 를 호출하되
    다음 두 가지를 생략해 대폭 가볍게 만든다:
      1. 이미지 실체화 (Phase B) — 전혀 실행하지 않음.
      2. 실제 image_records / annotations 로드 — 빈 리스트로 stub.
         head_schema/classes 변환은 image_records 가 비어있어도
         정상 동작하도록 각 manipulator 가 이미 작성되어 있음.

이 모듈은 app/ 레이어 및 DB 에 의존하지 않는다. 호출자(service 레이어)
가 각 source dataset_id 에 대한 `head_schema` 를 미리 DB 에서 로드해
source_meta_by_dataset_id 로 전달한다.
"""
from __future__ import annotations

import logging
from typing import Any

from lib.manipulators import MANIPULATOR_REGISTRY
from lib.pipeline.config import PipelineConfig
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema

logger = logging.getLogger(__name__)


class SchemaPreviewError(Exception):
    """프리뷰 계산 중 발생한 사용자 노출용 에러."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_stub_source_meta(
    dataset_id: str,
    head_schema_json: dict[str, Any] | None,
) -> DatasetMeta:
    """
    DB 에서 읽은 source dataset 의 head_schema JSONB 를 stub DatasetMeta 로 변환.

    head_schema_json 예:
        {"heads": [{"name": "hat", "multi_label": false, "classes": ["yes", "no"]}]}

    head_schema_json 이 None/빈 값이면 detection 소스로 간주하고
    head_schema=None 인 stub 을 반환한다.
    """
    head_schema_list: list[HeadSchema] | None = None
    if head_schema_json:
        raw_heads = head_schema_json.get("heads") or []
        if raw_heads:
            head_schema_list = [
                HeadSchema(
                    name=str(head.get("name", "")),
                    multi_label=bool(head.get("multi_label", False)),
                    classes=[str(name) for name in (head.get("classes") or [])],
                )
                for head in raw_heads
            ]

    return DatasetMeta(
        dataset_id=dataset_id,
        storage_uri="",
        categories=[],
        image_records=[],
        head_schema=head_schema_list,
    )


def preview_head_schema_at_task(
    config: PipelineConfig,
    target_task_name: str,
    source_meta_by_dataset_id: dict[str, DatasetMeta],
) -> DatasetMeta:
    """
    target_task_name 이 가리키는 task 의 **출력** DatasetMeta 를 반환한다.

    transform_annotation 만 호출하고 이미지 실체화는 생략.
    image_records 는 stub([]) 으로 흐르므로, image_records 순회 기반 로직은
    no-op 이 된다. manipulator 가 head_schema 가 None 인 DatasetMeta 에
    대해 에러를 던지는 경우(예: cls_* ) 는 Classification 파이프라인에서만
    쓰이므로 문제 없음.

    Raises:
        SchemaPreviewError: target_task_name 이 config 에 없거나 의존 태스크가
            누락되었을 때.
    """
    if target_task_name not in config.tasks:
        raise SchemaPreviewError(
            code="TARGET_NOT_FOUND",
            message=f"target_task '{target_task_name}' 가 config.tasks 에 없습니다.",
        )

    execution_order = config.topological_order()

    # target 이후 task 는 계산 불필요. target 직전까지만 순회하고 target 처리 후 break.
    task_results: dict[str, DatasetMeta] = {}

    for task_name in execution_order:
        task_config = config.tasks[task_name]

        input_metas: list[DatasetMeta] = []
        for ref in task_config.inputs:
            if ref.startswith("source:"):
                dataset_id = ref.split(":", 1)[1]
                source_meta = source_meta_by_dataset_id.get(dataset_id)
                if source_meta is None:
                    raise SchemaPreviewError(
                        code="SOURCE_NOT_LOADED",
                        message=(
                            f"source dataset_id='{dataset_id}' 의 head_schema 를 "
                            f"로드하지 못했습니다 (task='{task_name}')."
                        ),
                    )
                input_metas.append(source_meta)
            else:
                upstream_meta = task_results.get(ref)
                if upstream_meta is None:
                    raise SchemaPreviewError(
                        code="UPSTREAM_MISSING",
                        message=(
                            f"task '{task_name}' 의 입력 '{ref}' 가 아직 계산되지 "
                            f"않았습니다 (topological order 오류)."
                        ),
                    )
                input_metas.append(upstream_meta)

        result_meta = _apply_manipulator_for_preview(
            input_metas, task_config.operator, task_config.params,
        )
        task_results[task_name] = result_meta

        if task_name == target_task_name:
            return result_meta

    # 여기까지 오면 target 이 topological order 에 포함되지 않은 것 — 이론상 불가.
    raise SchemaPreviewError(
        code="TARGET_UNREACHABLE",
        message=f"target_task '{target_task_name}' 가 topological order 에 없습니다.",
    )


def _apply_manipulator_for_preview(
    input_metas: list[DatasetMeta],
    operator_name: str,
    params: dict[str, Any],
) -> DatasetMeta:
    """프리뷰용 manipulator 적용. dag_executor 와 동일한 dispatch 규칙."""
    manipulator_class = MANIPULATOR_REGISTRY.get(operator_name)
    if manipulator_class is None:
        raise SchemaPreviewError(
            code="UNKNOWN_OPERATOR",
            message=f"등록되지 않은 operator: {operator_name}",
        )

    instance = manipulator_class()
    accepts_multi = getattr(manipulator_class, "accepts_multi_input", False)

    try:
        if accepts_multi:
            return instance.transform_annotation(input_metas, params)
        if len(input_metas) == 1:
            return instance.transform_annotation(input_metas[0], params)
        # 일반 manipulator 에 다중 입력이 들어오면 의미가 모호 — 프리뷰는 첫 입력만.
        # (dag_executor 는 _merge_metas 를 호출하지만 detection 전용 로직이라 스킵.)
        return instance.transform_annotation(input_metas[0], params)
    except NotImplementedError as not_impl:
        raise SchemaPreviewError(
            code="OPERATOR_NOT_IMPLEMENTED",
            message=(
                f"operator '{operator_name}' 는 아직 구현되지 않아 프리뷰를 "
                f"생성할 수 없습니다: {not_impl}"
            ),
        ) from not_impl
    except (ValueError, TypeError) as transform_error:
        # params 가 비었거나 mapping 이 잘못된 경우 — 사용자 입력 문제.
        raise SchemaPreviewError(
            code="TRANSFORM_FAILED",
            message=(
                f"operator '{operator_name}' 변환 실패: {transform_error}"
            ),
        ) from transform_error


def head_schema_to_list(
    head_schema: list[HeadSchema] | None,
) -> list[dict[str, Any]] | None:
    """HeadSchema 리스트 → API 응답용 dict 리스트.

    API 응답은 DB JSONB 의 {"heads": [...]} wrapper 대신 리스트를 그대로 돌려준다.
    """
    if head_schema is None:
        return None
    return [
        {
            "name": head.name,
            "multi_label": head.multi_label,
            "classes": list(head.classes),
        }
        for head in head_schema
    ]
