"""
파이프라인 API 라우터 (v7.11 — feature/pipeline-family-and-version).

라우트 그룹:
  - PipelineRun (실행 이력 / 제출 / 상태)              — `/api/v1/pipelines/runs/*`
  - Pipeline (concept) CRUD                             — `/api/v1/pipelines/{id}`
  - PipelineVersion (config + version 인스턴스)         — `/api/v1/pipelines/versions/{id}`
  - PipelineFamily (즐겨찾기 폴더)                       — `/api/v1/pipelines/families/*`
  - PipelineAutomation (version 단위 runner)            — `/api/v1/pipelines/automations/*`
  - validate / preview-schema / execute (편의)           — `/api/v1/pipelines/{validate,...}`

`/api/v1/pipelines` 가 이 라우터의 prefix. 위 sub-path 는 그 하위.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.storage import get_storage_client
from app.models.all_models import (
    Pipeline,
    PipelineAutomation,
    PipelineFamily,
    PipelineRun,
    PipelineVersion,
)
from app.schemas.pipeline import (
    PipelineAutomationRerunRequest,
    PipelineAutomationResponse,
    PipelineAutomationUpsertRequest,
    PipelineConfig,
    PipelineFamilyCreateRequest,
    PipelineFamilyResponse,
    PipelineFamilyUpdateRequest,
    PipelineListItemResponse,
    PipelineListPageResponse,
    PipelineListResponse,
    PipelineResponse,
    PipelineRunResponse,
    PipelineRunSubmitRequest,
    PipelineSaveResponse,
    PipelineSubmitResponse,
    PipelineUpdateRequest,
    PipelineValidationIssueResponse,
    PipelineValidationResponse,
    PipelineVersionResponse,
    PipelineVersionSummary,
    PipelineVersionUpdateRequest,
    SchemaPreviewRequest,
    SchemaPreviewResponse,
)
from app.services.pipeline_automation_service import PipelineAutomationService
from app.services.pipeline_service import PipelineService

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# 공통 빌더
# ─────────────────────────────────────────────────────────────────────────────

def _build_run_response(run: PipelineRun) -> PipelineRunResponse:
    """PipelineRun ORM → PipelineRunResponse. output_dataset 선로드 전제."""
    pipeline_image_url = None
    output_dataset = run.output_dataset
    if output_dataset and output_dataset.storage_uri:
        storage = get_storage_client()
        png_path = storage.resolve_path(output_dataset.storage_uri) / "pipeline.png"
        if png_path.exists():
            pipeline_image_url = storage.get_image_serve_url(
                f"{output_dataset.storage_uri}/pipeline.png"
            )

    output_dataset_version = None
    output_dataset_group_id = None
    if output_dataset:
        output_dataset_version = output_dataset.version
        output_dataset_group_id = output_dataset.group_id

    return PipelineRunResponse(
        id=run.id,
        output_dataset_id=run.output_dataset_id,
        config=run.transform_config,
        status=run.status,
        current_stage=run.current_stage,
        processed_count=run.processed_count,
        total_count=run.total_count,
        error_message=run.error_message,
        celery_task_id=run.celery_task_id,
        task_progress=run.task_progress,
        pipeline_image_url=pipeline_image_url,
        output_dataset_version=output_dataset_version,
        output_dataset_group_id=output_dataset_group_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


def _pydantic_errors_to_issues(exc) -> list[PipelineValidationIssueResponse]:
    """Pydantic ValidationError → 친화적 issue 목록."""
    return [
        PipelineValidationIssueResponse(
            severity="error",
            code=str(err.get("type", "VALIDATION_ERROR")).upper(),
            message=err.get("msg", "검증 실패"),
            field=".".join(str(x) for x in err.get("loc", []) if x not in ("body",)),
        )
        for err in exc.errors()
    ]


def _version_summary(version: PipelineVersion) -> PipelineVersionSummary:
    return PipelineVersionSummary(
        id=version.id,
        version=version.version,
        is_active=version.is_active,
        has_automation=getattr(version, "automation", None) is not None,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _pipeline_to_response(pipeline: Pipeline) -> PipelineResponse:
    """Pipeline (concept) ORM → 응답. family / output_split / versions 선로드 전제."""
    output_split = pipeline.output_split
    output_group = output_split.group if output_split else None
    family = pipeline.family
    versions_sorted = sorted(
        list(pipeline.versions or []),
        key=lambda v: v.created_at, reverse=True,
    )
    versions_summaries = [_version_summary(v) for v in versions_sorted]
    latest_active = next(
        (v for v in versions_summaries if v.is_active), None,
    )
    return PipelineResponse(
        id=pipeline.id,
        family_id=pipeline.family_id,
        family_name=family.name if family else None,
        name=pipeline.name,
        description=pipeline.description,
        output_split_id=pipeline.output_split_id,
        output_group_id=output_group.id if output_group else None,
        output_group_name=output_group.name if output_group else None,
        output_split=output_split.split if output_split else None,
        task_type=pipeline.task_type,
        is_active=pipeline.is_active,
        versions=versions_summaries,
        latest_version=latest_active,
        created_at=pipeline.created_at,
        updated_at=pipeline.updated_at,
    )


def _pipeline_to_list_item(
    pipeline: Pipeline,
    *,
    run_count: int = 0,
    last_run_at=None,
) -> PipelineListItemResponse:
    output_split = pipeline.output_split
    output_group = output_split.group if output_split else None
    family = pipeline.family
    active_versions = [v for v in (pipeline.versions or []) if v.is_active]
    latest_version_str: str | None = None
    has_automation = False
    if active_versions:
        latest = sorted(active_versions, key=lambda v: v.created_at, reverse=True)[0]
        latest_version_str = latest.version
        has_automation = getattr(latest, "automation", None) is not None
    return PipelineListItemResponse(
        id=pipeline.id,
        family_id=pipeline.family_id,
        family_name=family.name if family else None,
        name=pipeline.name,
        description=pipeline.description,
        output_split_id=pipeline.output_split_id,
        output_group_id=output_group.id if output_group else None,
        output_group_name=output_group.name if output_group else None,
        output_split=output_split.split if output_split else None,
        task_type=pipeline.task_type,
        is_active=pipeline.is_active,
        version_count=len(pipeline.versions or []),
        latest_version=latest_version_str,
        has_automation=has_automation,
        run_count=run_count,
        last_run_at=last_run_at,
        created_at=pipeline.created_at,
        updated_at=pipeline.updated_at,
    )


def _version_to_response(version: PipelineVersion) -> PipelineVersionResponse:
    pipeline = version.pipeline
    output_split = pipeline.output_split if pipeline else None
    output_group = output_split.group if output_split else None
    family = pipeline.family if pipeline else None
    return PipelineVersionResponse(
        id=version.id,
        pipeline_id=version.pipeline_id,
        pipeline_name=pipeline.name if pipeline else "",
        family_id=pipeline.family_id if pipeline else None,
        family_name=family.name if family else None,
        version=version.version,
        config=version.config,
        task_type=pipeline.task_type if pipeline else "",
        output_split_id=pipeline.output_split_id if pipeline else "",
        output_group_id=output_group.id if output_group else None,
        output_group_name=output_group.name if output_group else None,
        output_split=output_split.split if output_split else None,
        is_active=version.is_active,
        has_automation=getattr(version, "automation", None) is not None,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _automation_to_response(automation: PipelineAutomation) -> PipelineAutomationResponse:
    pipeline_version = getattr(automation, "pipeline_version", None)
    pipeline = pipeline_version.pipeline if pipeline_version else None
    return PipelineAutomationResponse(
        id=automation.id,
        pipeline_version_id=automation.pipeline_version_id,
        pipeline_id=pipeline.id if pipeline else None,
        pipeline_name=pipeline.name if pipeline else None,
        pipeline_version=pipeline_version.version if pipeline_version else None,
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


def _family_to_response(family: PipelineFamily) -> PipelineFamilyResponse:
    pipeline_count = len(
        [p for p in (family.pipelines or []) if p.is_active]
    ) if hasattr(family, "pipelines") else 0
    return PipelineFamilyResponse(
        id=family.id,
        name=family.name,
        description=family.description,
        color=family.color,
        pipeline_count=pipeline_count,
        created_at=family.created_at,
        updated_at=family.updated_at,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Validate / Preview / Execute (FE 호환 진입점)
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/validate", response_model=PipelineValidationResponse)
async def validate_pipeline(
    config_dict: dict,
    db: AsyncSession = Depends(get_db),
):
    """파이프라인 설정 검증. Pydantic 422 는 issue 로 평탄화 응답."""
    from pydantic import ValidationError
    try:
        config = PipelineConfig(**config_dict)
    except ValidationError as exc:
        issues = _pydantic_errors_to_issues(exc)
        return PipelineValidationResponse(
            is_valid=False,
            error_count=len(issues),
            warning_count=0,
            issues=issues,
        )
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
    """DAG 노드 시점 head_schema 프리뷰."""
    service = PipelineService(db)
    preview_dict = await service.preview_head_schema(
        config=payload.config,
        target_ref=payload.target_ref,
    )
    return SchemaPreviewResponse(**preview_dict)


@router.post(
    "/concepts", response_model=PipelineSaveResponse, status_code=201,
)
async def save_pipeline_concept(
    config_dict: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    에디터에서 "저장" — config 를 Pipeline (concept) + PipelineVersion 으로 저장 (§12-1).

    실행 (PipelineRun + Celery dispatch) 은 분리된 흐름:
      - 목록의 행 우측 "실행" 버튼 → Version Resolver Modal
      - `POST /pipelines/versions/{id}/runs`
    """
    from pydantic import ValidationError
    try:
        config = PipelineConfig(**config_dict)
    except ValidationError as exc:
        issues = _pydantic_errors_to_issues(exc)
        first_msg = issues[0].message if issues else "config 형식이 잘못되었습니다."
        raise HTTPException(status_code=400, detail=first_msg) from exc
    service = PipelineService(db)
    return await service.save_pipeline_from_config(config)


# ═════════════════════════════════════════════════════════════════════════════
# PipelineRun (실행 이력) — `/runs`
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/runs", response_model=PipelineListResponse)
async def list_pipeline_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """전체 PipelineRun 이력 목록 (최신순)."""
    service = PipelineService(db)
    items, total = await service.list_executions(page=page, page_size=page_size)
    return PipelineListResponse(
        items=[_build_run_response(item) for item in items],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=PipelineRunResponse)
async def get_pipeline_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """PipelineRun 단건 상태."""
    service = PipelineService(db)
    run = await service.get_execution_status(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="실행 이력을 찾을 수 없습니다.")
    return _build_run_response(run)


# ═════════════════════════════════════════════════════════════════════════════
# PipelineFamily — `/families`
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/families", response_model=list[PipelineFamilyResponse])
async def list_families(db: AsyncSession = Depends(get_db)):
    service = PipelineService(db)
    families = await service.list_families()
    # pipeline_count 채우기 위해 selectinload 가 안 돼 있을 수 있음 — 빈 리스트 안전
    return [_family_to_response(f) for f in families]


@router.post(
    "/families", response_model=PipelineFamilyResponse, status_code=201,
)
async def create_family(
    payload: PipelineFamilyCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = PipelineService(db)
    family = await service.create_family(
        name=payload.name, description=payload.description, color=payload.color,
    )
    return _family_to_response(family)


@router.get("/families/{family_id}", response_model=PipelineFamilyResponse)
async def get_family(family_id: str, db: AsyncSession = Depends(get_db)):
    service = PipelineService(db)
    family = await service.get_family(family_id)
    if family is None:
        raise HTTPException(status_code=404, detail="Family 를 찾을 수 없습니다.")
    return _family_to_response(family)


@router.patch("/families/{family_id}", response_model=PipelineFamilyResponse)
async def update_family(
    family_id: str,
    payload: PipelineFamilyUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = PipelineService(db)
    family = await service.update_family(
        family_id,
        name=payload.name,
        description=payload.description,
        color=payload.color,
    )
    if family is None:
        raise HTTPException(status_code=404, detail="Family 를 찾을 수 없습니다.")
    return _family_to_response(family)


@router.delete("/families/{family_id}", status_code=204)
async def delete_family(family_id: str, db: AsyncSession = Depends(get_db)):
    """Family hard delete. 자식 Pipeline 들은 family_id NULL 로 (ON DELETE SET NULL)."""
    service = PipelineService(db)
    deleted = await service.delete_family(family_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Family 를 찾을 수 없습니다.")


# ═════════════════════════════════════════════════════════════════════════════
# PipelineVersion — `/versions/{id}`
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/versions/{version_id}", response_model=PipelineVersionResponse)
async def get_pipeline_version(
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    """PipelineVersion 상세 — config 포함."""
    service = PipelineService(db)
    version = await service.get_pipeline_version(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="PipelineVersion 을 찾을 수 없습니다.")
    return _version_to_response(version)


@router.patch("/versions/{version_id}", response_model=PipelineVersionResponse)
async def update_pipeline_version(
    version_id: str,
    payload: PipelineVersionUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """PipelineVersion 편집 — is_active 토글만. config 는 immutable."""
    service = PipelineService(db)
    version = await service.update_pipeline_version(
        version_id, is_active=payload.is_active,
    )
    if version is None:
        raise HTTPException(status_code=404, detail="PipelineVersion 을 찾을 수 없습니다.")
    return _version_to_response(version)


@router.get("/versions/{version_id}/runs", response_model=PipelineListResponse)
async def list_runs_of_version(
    version_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """이 PipelineVersion 의 PipelineRun 이력."""
    service = PipelineService(db)
    offset = (page - 1) * page_size
    items, total = await service.list_runs_by_pipeline_version(
        version_id, limit=page_size, offset=offset,
    )
    return PipelineListResponse(
        items=[_build_run_response(item) for item in items],
        total=total,
    )


@router.post(
    "/versions/{version_id}/runs",
    response_model=PipelineSubmitResponse,
    status_code=202,
)
async def submit_run_for_version(
    version_id: str,
    payload: PipelineRunSubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Version Resolver Modal → PipelineVersion 기반 run dispatch."""
    service = PipelineService(db)
    try:
        return await service.submit_run_from_pipeline_version(
            version_id, payload.resolved_input_versions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ═════════════════════════════════════════════════════════════════════════════
# PipelineAutomation — `/automations` (version 단위)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/automations", response_model=list[PipelineAutomationResponse])
async def list_active_automations(db: AsyncSession = Depends(get_db)):
    service = PipelineAutomationService(db)
    automations = await service.list_all_active()
    return [_automation_to_response(a) for a in automations]


@router.get(
    "/versions/{version_id}/automation",
    response_model=PipelineAutomationResponse | None,
)
async def get_version_automation(
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    """PipelineVersion 의 현재 active automation. 없으면 null."""
    service = PipelineAutomationService(db)
    automation = await service.get_active_by_pipeline_version(version_id)
    if automation is None:
        return None
    return _automation_to_response(automation)


@router.put(
    "/versions/{version_id}/automation",
    response_model=PipelineAutomationResponse,
)
async def upsert_version_automation(
    version_id: str,
    payload: PipelineAutomationUpsertRequest,
    db: AsyncSession = Depends(get_db),
):
    """PipelineVersion 의 automation 등록 또는 갱신."""
    service = PipelineAutomationService(db)
    try:
        automation = await service.upsert_automation(version_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _automation_to_response(automation)


@router.delete(
    "/automations/{automation_id}", response_model=PipelineAutomationResponse,
)
async def delete_automation(
    automation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Automation soft delete."""
    service = PipelineAutomationService(db)
    automation = await service.soft_delete(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation 을 찾을 수 없습니다.")
    return _automation_to_response(automation)


@router.post(
    "/automations/{automation_id}/reassign",
    response_model=PipelineAutomationResponse,
)
async def reassign_automation(
    automation_id: str,
    new_pipeline_version_id: str = Query(
        ..., description="새 target PipelineVersion ID",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Automation 을 다른 PipelineVersion 으로 이전."""
    service = PipelineAutomationService(db)
    try:
        automation = await service.reassign_pipeline_version(
            automation_id, new_pipeline_version_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation 을 찾을 수 없습니다.")
    return _automation_to_response(automation)


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
    """수동 재실행 (if_delta / force_latest)."""
    service = PipelineAutomationService(db)
    try:
        return await service.trigger_manual_rerun(automation_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ═════════════════════════════════════════════════════════════════════════════
# Pipeline (concept) CRUD — `/{pipeline_id}` (마지막에 와야 정적 경로 우선)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("", response_model=PipelineListPageResponse)
async def list_pipelines(
    include_inactive: bool = Query(False),
    name_filter: str | None = Query(None, description="name ILIKE 부분 일치"),
    task_type: list[str] | None = Query(None),
    family_id: list[str] | None = Query(None, description="이 family 들의 Pipeline (다중, OR)"),
    family_unfiled: bool = Query(False, description="미분류 (family_id IS NULL) 도 포함 (다른 family_id 와 OR)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Pipeline (concept) 목록."""
    service = PipelineService(db)
    items, total = await service.list_pipelines(
        include_inactive=include_inactive,
        name_filter=name_filter,
        task_type_filter=task_type,
        family_id=family_id,
        family_unfiled=family_unfiled,
        limit=limit,
        offset=offset,
    )
    pipeline_ids = [p.id for p in items]
    run_stats = await service.count_runs_by_pipeline(pipeline_ids)
    response_items = []
    for pipeline in items:
        run_count, last_run_at = run_stats.get(pipeline.id, (0, None))
        response_items.append(
            _pipeline_to_list_item(
                pipeline, run_count=run_count, last_run_at=last_run_at,
            )
        )
    return PipelineListPageResponse(
        items=response_items, total=total, limit=limit, offset=offset,
    )


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline_concept(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Pipeline (concept) 단건 — 모든 versions 요약 포함."""
    service = PipelineService(db)
    pipeline = await service.get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline 을 찾을 수 없습니다.")
    return _pipeline_to_response(pipeline)


@router.patch("/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline_concept(
    pipeline_id: str,
    payload: PipelineUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Pipeline (concept) 편집 — name / description / family_id / is_active."""
    if payload.unset_family and payload.family_id is not None:
        raise HTTPException(
            status_code=400,
            detail="unset_family 와 family_id 를 동시에 지정할 수 없습니다.",
        )
    service = PipelineService(db)
    pipeline = await service.update_pipeline(
        pipeline_id,
        name=payload.name,
        description=payload.description,
        family_id=payload.family_id,
        unset_family=payload.unset_family,
        is_active=payload.is_active,
    )
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline 을 찾을 수 없습니다.")
    return _pipeline_to_response(pipeline)


@router.get("/{pipeline_id}/runs", response_model=PipelineListResponse)
async def list_runs_of_pipeline(
    pipeline_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """이 Pipeline (concept) 의 모든 version 에 걸친 run 이력."""
    service = PipelineService(db)
    offset = (page - 1) * page_size
    items, total = await service.list_runs_by_pipeline(
        pipeline_id, limit=page_size, offset=offset,
    )
    return PipelineListResponse(
        items=[_build_run_response(item) for item in items],
        total=total,
    )
