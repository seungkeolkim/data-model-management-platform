"""
Dataset Groups API Router - Phase 1 구현

라우터 순서 주의사항:
- 정적 경로(/validate-path, /register)를 동적 경로(/{group_id}) 보다 먼저 등록해야 함
- FastAPI는 등록 순서대로 경로를 매칭하므로 /{group_id}가 먼저 등록되면
  /validate-path 요청이 group_id="validate-path"로 잘못 매칭됨
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
    DatasetValidateRequest,
    DatasetValidateResponse,
    MessageResponse,
)
from app.services.dataset_service import DatasetGroupService

router = APIRouter()


# =============================================================================
# 정적 경로 먼저 등록 (동적 /{group_id} 보다 앞에 위치해야 함)
# =============================================================================

@router.post("/validate-path", response_model=DatasetValidateResponse)
async def validate_storage_path(
    req: DatasetValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    NAS 경로 유효성 검사 (등록 전 경로 확인).

    - 경로 존재 여부 확인
    - images/ 디렉토리 존재 여부 확인
    - annotation.json 존재 및 COCO 포맷 검증
    """
    svc = DatasetGroupService(db)
    return svc.validate_storage_uri(req.storage_uri)


@router.post("/register", response_model=DatasetGroupResponse, status_code=201)
async def register_dataset(
    req: DatasetRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    GUI 방식 데이터셋 등록.

    NAS 경로를 지정하여 Dataset 등록 (그룹 신규 생성 또는 기존 그룹에 추가).

    등록 과정:
    1. NAS 경로 검증 (경로 존재 + COCO annotation 유효성)
    2. DatasetGroup 신규 생성 또는 기존 그룹에 추가
    3. Dataset(split/version) DB 저장
    """
    svc = DatasetGroupService(db)
    try:
        group, dataset = await svc.register_dataset(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 등록 후 전체 그룹 정보 반환
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
