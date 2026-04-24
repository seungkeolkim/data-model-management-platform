"""
파이프라인 실행 API 라우터.

POST /execute       — 파이프라인 제출 (Celery 비동기 실행)
GET /{id}/status    — 실행 상태 조회
GET /               — 실행 이력 목록
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.storage import get_storage_client
from app.models.all_models import PipelineRun
from app.schemas.pipeline import (
    PipelineConfig,
    PipelineRunResponse,
    PipelineListResponse,
    PipelineSubmitResponse,
    PipelineValidationIssueResponse,
    PipelineValidationResponse,
    SchemaPreviewRequest,
    SchemaPreviewResponse,
)
from app.services.pipeline_service import PipelineService

router = APIRouter()


def _build_execution_response(execution: PipelineRun) -> PipelineRunResponse:
    """
    PipelineRun ORM → PipelineRunResponse 변환.

    pipeline_image_url은 output_dataset의 storage_uri를 통해 생성한다.
    output_dataset relationship이 로드된 상태여야 한다.
    """
    pipeline_image_url = None
    output_dataset = execution.output_dataset
    if output_dataset and output_dataset.storage_uri:
        storage = get_storage_client()
        png_path = storage.resolve_path(output_dataset.storage_uri) / "pipeline.png"
        if png_path.exists():
            pipeline_image_url = storage.get_image_serve_url(
                f"{output_dataset.storage_uri}/pipeline.png"
            )

    # 출력 데이터셋 버전 및 그룹 ID
    output_dataset_version = None
    output_dataset_group_id = None
    if output_dataset:
        output_dataset_version = output_dataset.version
        output_dataset_group_id = output_dataset.group_id

    return PipelineRunResponse(
        id=execution.id,
        output_dataset_id=execution.output_dataset_id,
        config=execution.transform_config,
        status=execution.status,
        current_stage=execution.current_stage,
        processed_count=execution.processed_count,
        total_count=execution.total_count,
        error_message=execution.error_message,
        celery_task_id=execution.celery_task_id,
        task_progress=execution.task_progress,
        pipeline_image_url=pipeline_image_url,
        output_dataset_version=output_dataset_version,
        output_dataset_group_id=output_dataset_group_id,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        created_at=execution.created_at,
    )


@router.post("/validate", response_model=PipelineValidationResponse)
async def validate_pipeline(
    config: PipelineConfig,
    db: AsyncSession = Depends(get_db),
):
    """
    파이프라인 설정을 실행 전에 검증한다.

    정적 검증(operator 존재, 입력 수, output 유효성)과
    DB 검증(source dataset 존재/상태)을 모두 수행한다.

    is_valid가 False이면 error 수준의 문제가 있어 실행할 수 없다.
    issues 배열에 개별 사유가 담긴다.
    """
    service = PipelineService(db)
    validation_result = await service.validate_pipeline(config)

    return PipelineValidationResponse(
        is_valid=validation_result.is_valid,
        error_count=validation_result.error_count,
        warning_count=validation_result.warning_count,
        issues=[
            PipelineValidationIssueResponse(
                severity=issue.severity.value,
                code=issue.code,
                message=issue.message,
                field=issue.field,
            )
            for issue in validation_result.issues
        ],
    )


@router.post("/preview-schema", response_model=SchemaPreviewResponse)
async def preview_schema(
    payload: SchemaPreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    DAG 의 특정 노드 시점에서 head_schema 가 어떻게 변할지 계산한다.

    실제 이미지 실체화 없이 transform_annotation 만 호출하므로 수 ms 수준.
    Classification 파이프라인에서 속성 패널의 schema 프리뷰를 그리기 위해 사용한다.
    Detection 파이프라인(소스에 head_schema 가 없음)은 task_kind='detection' 으로
    반환되며 head_schema 는 None.
    """
    service = PipelineService(db)
    preview_dict = await service.preview_head_schema(
        config=payload.config,
        target_ref=payload.target_ref,
    )
    return SchemaPreviewResponse(**preview_dict)


@router.post("/execute", response_model=PipelineSubmitResponse, status_code=202)
async def execute_pipeline(
    config: PipelineConfig,
    db: AsyncSession = Depends(get_db),
):
    """
    파이프라인 실행을 제출한다.

    요청 본문으로 PipelineConfig JSON을 받아
    Celery 워커에 비동기 실행을 위임한다.
    즉시 execution_id를 반환하며, 실행 상태는 GET /{id}/status로 조회한다.
    """
    service = PipelineService(db)
    return await service.submit_pipeline(config)


@router.get("/{execution_id}/status", response_model=PipelineRunResponse)
async def get_pipeline_status(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
):
    """파이프라인 실행 상태를 조회한다."""
    service = PipelineService(db)
    execution = await service.get_execution_status(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="실행 이력을 찾을 수 없습니다.")
    return _build_execution_response(execution)


@router.get("", response_model=PipelineListResponse)
async def list_pipeline_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """파이프라인 실행 이력 목록을 조회한다."""
    service = PipelineService(db)
    items, total = await service.list_executions(page=page, page_size=page_size)
    return PipelineListResponse(
        items=[_build_execution_response(item) for item in items],
        total=total,
    )
