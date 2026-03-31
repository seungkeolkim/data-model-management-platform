"""
Dataset Groups API Router - Phase 1 구현

라우터 순서 주의사항:
- 정적 경로(/register)를 동적 경로(/{group_id}) 보다 먼저 등록해야 함
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.dataset import (
    DatasetGroupCreate,
    DatasetGroupListResponse,
    DatasetGroupResponse,
    DatasetGroupUpdate,
    DatasetRegisterRequest,
    MessageResponse,
)
from app.services.dataset_service import DatasetGroupService

router = APIRouter()


# =============================================================================
# 정적 경로 먼저 등록 (동적 /{group_id} 보다 앞에 위치해야 함)
# =============================================================================

@router.post("/register", response_model=DatasetGroupResponse, status_code=201)
async def register_dataset(
    req: DatasetRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    GUI 방식 데이터셋 등록 (파일 브라우저).

    source_image_dir 과 source_annotation_files 를 지정하면
    플랫폼이 관리 스토리지로 파일을 복사하고 DB에 등록합니다.
    버전은 자동 생성되며 원본 파일은 삭제되지 않습니다.
    """
    svc = DatasetGroupService(db)
    try:
        group, dataset = await svc.register_dataset(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return await svc.get_group(group.id)


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
    svc = DatasetGroupService(db)
    groups, total = await svc.list_groups(
        page=page,
        page_size=page_size,
        dataset_type=dataset_type,
        search=search,
    )
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
    svc = DatasetGroupService(db)
    group = await svc.create_group(data)
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
    svc = DatasetGroupService(db)
    group = await svc.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="DatasetGroup not found")
    return group


@router.patch("/{group_id}", response_model=DatasetGroupResponse)
async def update_dataset_group(
    group_id: str,
    data: DatasetGroupUpdate,
    db: AsyncSession = Depends(get_db),
):
    """데이터셋 그룹 수정 (부분 업데이트)."""
    svc = DatasetGroupService(db)
    group = await svc.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="DatasetGroup not found")
    updated = await svc.update_group(group, data)
    return updated


@router.delete("/{group_id}", response_model=MessageResponse)
async def delete_dataset_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """데이터셋 그룹 삭제."""
    svc = DatasetGroupService(db)
    group = await svc.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="DatasetGroup not found")
    await svc.delete_group(group)
    return MessageResponse(message=f"DatasetGroup {group_id} deleted")
