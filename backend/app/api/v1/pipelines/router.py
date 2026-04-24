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
from app.models.all_models import Pipeline, PipelineAutomation, PipelineRun
from app.schemas.pipeline import (
    PipelineAutomationRerunRequest,
    PipelineAutomationResponse,
    PipelineAutomationUpsertRequest,
    PipelineConfig,
    PipelineListItemResponse,
    PipelineListPageResponse,
    PipelineListResponse,
    PipelineResponse,
    PipelineRunResponse,
    PipelineRunSubmitRequest,
    PipelineSubmitResponse,
    PipelineUpdateRequest,
    PipelineValidationIssueResponse,
    PipelineValidationResponse,
    SchemaPreviewRequest,
    SchemaPreviewResponse,
)
from app.services.pipeline_automation_service import PipelineAutomationService
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


# =============================================================================
# Pipeline 엔티티 CRUD (v7.10, 핸드오프 027 §2-1 / §12)
#
# 경로 규약: path 충돌을 피하기 위해 `/entities` / `/automations` sub-path 사용.
# §9-7 페이지 재배선 시 정식 `/pipelines` top-level 로 승격 검토.
# =============================================================================


def _build_pipeline_list_item(
    pipeline: Pipeline,
    run_count: int = 0,
    last_run_at=None,
) -> PipelineListItemResponse:
    """Pipeline ORM → PipelineListItemResponse. output_split / automation 선로드 전제."""
    output_split = pipeline.output_split
    output_group = output_split.group if output_split else None
    return PipelineListItemResponse(
        id=pipeline.id,
        name=pipeline.name,
        version=pipeline.version,
        description=pipeline.description,
        output_split_id=pipeline.output_split_id,
        output_group_id=output_group.id if output_group else None,
        output_group_name=output_group.name if output_group else None,
        output_split=output_split.split if output_split else None,
        task_type=pipeline.task_type,
        is_active=pipeline.is_active,
        has_automation=pipeline.automation is not None,
        run_count=run_count,
        last_run_at=last_run_at,
        created_at=pipeline.created_at,
        updated_at=pipeline.updated_at,
    )


def _build_pipeline_response(pipeline: Pipeline) -> PipelineResponse:
    """Pipeline ORM → PipelineResponse (상세용, config 포함)."""
    output_split = pipeline.output_split
    output_group = output_split.group if output_split else None
    return PipelineResponse(
        id=pipeline.id,
        name=pipeline.name,
        version=pipeline.version,
        description=pipeline.description,
        output_split_id=pipeline.output_split_id,
        output_group_id=output_group.id if output_group else None,
        output_group_name=output_group.name if output_group else None,
        output_split=output_split.split if output_split else None,
        config=pipeline.config,
        task_type=pipeline.task_type,
        is_active=pipeline.is_active,
        has_automation=pipeline.automation is not None,
        created_at=pipeline.created_at,
        updated_at=pipeline.updated_at,
    )


def _build_automation_response(
    automation: PipelineAutomation,
) -> PipelineAutomationResponse:
    return PipelineAutomationResponse(
        id=automation.id,
        pipeline_id=automation.pipeline_id,
        status=automation.status,
        mode=automation.mode,
        poll_interval=automation.poll_interval,
        error_reason=automation.error_reason,
        last_seen_input_versions=automation.last_seen_input_versions,
        is_active=automation.is_active,
        deleted_at=automation.deleted_at,
        created_at=automation.created_at,
        updated_at=automation.updated_at,
    )


@router.get("/entities", response_model=PipelineListPageResponse)
async def list_pipeline_entities(
    include_inactive: bool = Query(
        False, description="FALSE (기본) 면 is_active=TRUE 만. legacy 숨김",
    ),
    name_filter: str | None = Query(None, description="name ILIKE 부분 일치"),
    task_type: list[str] | None = Query(None, description="DETECTION / CLASSIFICATION ..."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Pipeline 목록 — Automation 관리 페이지 좌측 + /pipelines 페이지 본체 (§9-7 예정).
    기본은 `is_active=TRUE` (§5-3 legacy 숨김 기본 ON).
    """
    service = PipelineService(db)
    items, total = await service.list_pipelines(
        include_inactive=include_inactive,
        name_filter=name_filter,
        task_type_filter=task_type,
        limit=limit,
        offset=offset,
    )
    pipeline_ids = [p.id for p in items]
    run_stats = await service.count_runs_by_pipeline(pipeline_ids)
    response_items = []
    for pipeline in items:
        run_count, last_run_at = run_stats.get(pipeline.id, (0, None))
        response_items.append(
            _build_pipeline_list_item(pipeline, run_count, last_run_at)
        )
    return PipelineListPageResponse(
        items=response_items, total=total, limit=limit, offset=offset,
    )


@router.get("/entities/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline_entity(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Pipeline 단건 상세 (config JSONB 포함)."""
    service = PipelineService(db)
    pipeline = await service.get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline 을 찾을 수 없습니다.")
    return _build_pipeline_response(pipeline)


@router.patch("/entities/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline_entity(
    pipeline_id: str,
    payload: PipelineUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Pipeline 편집 (§6-1 config immutable, §12-4 RBAC 없는 자유 편집).
    name / description / is_active 만 수정 가능. config 필드 변경은 거부된다.
    """
    service = PipelineService(db)
    pipeline = await service.update_pipeline(
        pipeline_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
    )
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline 을 찾을 수 없습니다.")
    return _build_pipeline_response(pipeline)


@router.get("/entities/{pipeline_id}/runs", response_model=PipelineListResponse)
async def list_runs_of_pipeline(
    pipeline_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """특정 Pipeline 의 실행 이력 (최신순)."""
    service = PipelineService(db)
    offset = (page - 1) * page_size
    items, total = await service.list_runs_by_pipeline(
        pipeline_id, limit=page_size, offset=offset,
    )
    return PipelineListResponse(
        items=[_build_execution_response(item) for item in items],
        total=total,
    )


@router.post(
    "/entities/{pipeline_id}/runs",
    response_model=PipelineSubmitResponse,
    status_code=202,
)
async def submit_run_for_pipeline(
    pipeline_id: str,
    payload: PipelineRunSubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Version Resolver Modal (027 §4-3) → 실제 dispatch 진입점.
    resolved_input_versions = `{split_id: version}` 확정값을 받아 run 1건 dispatch.
    """
    service = PipelineService(db)
    try:
        return await service.submit_run_from_pipeline(
            pipeline_id, payload.resolved_input_versions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─────────────────────────────────────────────────────────────────────────────
# PipelineAutomation (§2-3 + §12-3 soft delete)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/automations", response_model=list[PipelineAutomationResponse])
async def list_active_automations(
    db: AsyncSession = Depends(get_db),
):
    """활성 자동화 전체. Automation 관리 페이지 좌측 목록."""
    service = PipelineAutomationService(db)
    automations = await service.list_all_active()
    return [_build_automation_response(a) for a in automations]


@router.get(
    "/entities/{pipeline_id}/automation",
    response_model=PipelineAutomationResponse | None,
)
async def get_pipeline_automation(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Pipeline 의 현재 active automation. 없으면 null."""
    service = PipelineAutomationService(db)
    automation = await service.get_active_by_pipeline(pipeline_id)
    if automation is None:
        return None
    return _build_automation_response(automation)


@router.put(
    "/entities/{pipeline_id}/automation",
    response_model=PipelineAutomationResponse,
)
async def upsert_pipeline_automation(
    pipeline_id: str,
    payload: PipelineAutomationUpsertRequest,
    db: AsyncSession = Depends(get_db),
):
    """자동화 등록 또는 갱신 (idempotent). 같은 Pipeline active 가 있으면 덮어씀."""
    service = PipelineAutomationService(db)
    try:
        automation = await service.upsert_automation(pipeline_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_automation_response(automation)


@router.delete(
    "/automations/{automation_id}",
    response_model=PipelineAutomationResponse,
)
async def delete_automation(
    automation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """자동화 soft delete (§12-3). row 유지, is_active=FALSE + deleted_at=NOW()."""
    service = PipelineAutomationService(db)
    automation = await service.soft_delete(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation 을 찾을 수 없습니다.")
    return _build_automation_response(automation)


@router.post(
    "/automations/{automation_id}/reassign",
    response_model=PipelineAutomationResponse,
)
async def reassign_automation(
    automation_id: str,
    new_pipeline_id: str = Query(..., description="새 target Pipeline ID"),
    db: AsyncSession = Depends(get_db),
):
    """자동화가 가리키는 Pipeline 을 다른 Pipeline 으로 이전 (§6-4 (a))."""
    service = PipelineAutomationService(db)
    try:
        automation = await service.reassign_pipeline(automation_id, new_pipeline_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation 을 찾을 수 없습니다.")
    return _build_automation_response(automation)


@router.post(
    "/automations/{automation_id}/rerun",
    response_model=PipelineSubmitResponse,
    status_code=202,
)
async def trigger_manual_rerun(
    automation_id: str,
    payload: PipelineAutomationRerunRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    수동 재실행 — 026 §5-2a 2-버튼 UX.

    - if_delta: 상류 delta 있을 때만 dispatch, 없으면 SKIPPED_NO_DELTA 레코드
    - force_latest: delta 무시, 최신 version 으로 강제 dispatch
    """
    service = PipelineAutomationService(db)
    try:
        return await service.trigger_manual_rerun(automation_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
