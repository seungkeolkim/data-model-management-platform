"""
파이프라인 실행 API 라우터.

POST /execute       — 파이프라인 제출 (Celery 비동기 실행)
GET /{id}/status    — 실행 상태 조회
GET /               — 실행 이력 목록
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.pipeline import (
    PipelineConfig,
    PipelineExecutionResponse,
    PipelineListResponse,
    PipelineSubmitResponse,
    PipelineValidationIssueResponse,
    PipelineValidationResponse,
)
from app.services.pipeline_service import PipelineService

router = APIRouter()


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


@router.get("/{execution_id}/status", response_model=PipelineExecutionResponse)
async def get_pipeline_status(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
):
    """파이프라인 실행 상태를 조회한다."""
    service = PipelineService(db)
    execution = await service.get_execution_status(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="실행 이력을 찾을 수 없습니다.")
    return execution


@router.get("", response_model=PipelineListResponse)
async def list_pipeline_executions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """파이프라인 실행 이력 목록을 조회한다."""
    service = PipelineService(db)
    items, total = await service.list_executions(page=page, page_size=page_size)
    return PipelineListResponse(items=items, total=total)
