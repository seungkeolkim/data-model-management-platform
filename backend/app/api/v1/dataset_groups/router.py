"""
Dataset Groups API Router - Phase 1 구현

라우터 순서 주의사항:
- 정적 경로(/register)를 동적 경로(/{group_id}) 보다 먼저 등록해야 함
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.dataset import (
    DatasetGroupCreate,
    DatasetGroupListResponse,
    DatasetGroupResponse,
    DatasetGroupUpdate,
    DatasetRegisterRequest,
    FormatValidateRequest,
    FormatValidateResponse,
    MessageResponse,
)
from app.services.dataset_service import DatasetGroupService

logger = structlog.get_logger(__name__)

router = APIRouter()


# =============================================================================
# 정적 경로 먼저 등록 (동적 /{group_id} 보다 앞에 위치해야 함)
# =============================================================================

@router.post("/register", response_model=DatasetGroupResponse, status_code=202)
async def register_dataset(
    req: DatasetRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    GUI 방식 데이터셋 등록 (파일 브라우저).

    DB에 DatasetGroup + Dataset(PROCESSING)을 즉시 생성하고,
    파일 복사는 Celery worker에서 비동기로 수행합니다.
    복사 완료 시 READY, 실패 시 ERROR로 상태가 전이됩니다.
    """
    logger.info(
        "데이터셋 등록 요청 수신",
        group_id=req.group_id,
        group_name=req.group_name,
        split=req.split,
        annotation_format=req.annotation_format,
        source_image_dir=req.source_image_dir,
        annotation_file_count=len(req.source_annotation_files),
    )
    svc = DatasetGroupService(db)
    try:
        group, dataset = await svc.register_dataset(req)
    except ValueError as e:
        logger.warning("데이터셋 등록 실패 (검증 오류)", error=str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "데이터셋 등록 접수 (파일 복사 진행 중)",
        group_id=group.id,
        group_name=group.name,
        dataset_id=dataset.id,
        version=dataset.version,
        split=dataset.split,
    )
    return await svc.get_group(group.id)


@router.post("/validate-format", response_model=FormatValidateResponse)
async def validate_annotation_format(
    req: FormatValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    어노테이션 파일이 지정된 포맷에 맞는지 사전 검증.

    등록 전에 선택한 파일이 COCO/YOLO 등의 포맷 규격을 만족하는지 확인.
    검증 실패해도 등록을 차단하지는 않음 (경고 용도).
    """
    logger.info(
        "포맷 검증 요청",
        annotation_format=req.annotation_format,
        file_count=len(req.annotation_files),
    )
    svc = DatasetGroupService(db)
    result = svc.validate_annotation_format(req)
    logger.info("포맷 검증 완료", valid=result.valid, error_count=len(result.errors))
    return result


@router.get("/next-version")
async def get_next_version(
    group_id: str = Query(..., description="데이터셋 그룹 ID"),
    split: str = Query(..., description="TRAIN | VAL | TEST | NONE"),
    db: AsyncSession = Depends(get_db),
):
    """해당 그룹+split의 다음 자동 생성 버전 조회."""
    svc = DatasetGroupService(db)
    version = await svc._next_version(group_id, split)
    return {"version": version}


# =============================================================================
# 컬렉션 엔드포인트
# =============================================================================

@router.get("", response_model=DatasetGroupListResponse)
async def list_dataset_groups(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    dataset_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """데이터셋 그룹 목록 조회 (페이지네이션)."""
    logger.info("그룹 목록 조회", page=page, page_size=page_size, dataset_type=dataset_type, search=search)
    svc = DatasetGroupService(db)
    groups, total = await svc.list_groups(
        page=page,
        page_size=page_size,
        dataset_type=dataset_type,
        search=search,
    )
    logger.info("그룹 목록 조회 완료", total=total, returned=len(groups))
    return DatasetGroupListResponse(
        items=groups,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DatasetGroupResponse, status_code=201)
async def create_dataset_group(
    data: DatasetGroupCreate,
    db: AsyncSession = Depends(get_db),
):
    """데이터셋 그룹 생성."""
    logger.info("그룹 생성 요청", name=data.name, dataset_type=data.dataset_type)
    svc = DatasetGroupService(db)
    try:
        group = await svc.create_group(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    logger.info("그룹 생성 완료", group_id=group.id, name=group.name)
    return group


# =============================================================================
# 동적 경로 (/{group_id}) - 반드시 정적 경로 뒤에 등록
# =============================================================================

@router.get("/{group_id}", response_model=DatasetGroupResponse)
async def get_dataset_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """데이터셋 그룹 상세 조회."""
    logger.info("그룹 상세 조회", group_id=group_id)
    svc = DatasetGroupService(db)
    group = await svc.get_group(group_id)
    if not group:
        logger.warning("그룹 조회 실패 — 존재하지 않음", group_id=group_id)
        raise HTTPException(status_code=404, detail="DatasetGroup not found")
    return group


@router.patch("/{group_id}", response_model=DatasetGroupResponse)
async def update_dataset_group(
    group_id: str,
    data: DatasetGroupUpdate,
    db: AsyncSession = Depends(get_db),
):
    """데이터셋 그룹 수정 (부분 업데이트)."""
    logger.info("그룹 수정 요청", group_id=group_id)
    svc = DatasetGroupService(db)
    group = await svc.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="DatasetGroup not found")
    updated = await svc.update_group(group, data)
    logger.info("그룹 수정 완료", group_id=group_id)
    return updated


@router.delete("/{group_id}", response_model=MessageResponse)
async def delete_dataset_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """데이터셋 그룹 소프트 삭제. 하위 데이터셋도 함께 삭제되며 버전 이력은 보존된다."""
    logger.info("그룹 삭제 요청", group_id=group_id)
    svc = DatasetGroupService(db)
    group = await svc.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="DatasetGroup not found")
    deleted_dataset_count = await svc.delete_group(group)
    logger.info(
        "그룹 소프트 삭제 완료",
        group_id=group_id,
        name=group.name,
        deleted_dataset_count=deleted_dataset_count,
    )
    return MessageResponse(
        message=f"그룹 '{group.name}' 삭제 완료 (하위 데이터셋 {deleted_dataset_count}건 포함)"
    )
