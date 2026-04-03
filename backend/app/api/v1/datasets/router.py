"""
Datasets API Router (individual dataset operations)
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.all_models import Dataset, DatasetGroup
from app.schemas.dataset import (
    DatasetMetaFileReplaceRequest,
    DatasetResponse,
    DatasetUpdate,
    DatasetValidateRequest,
    FormatValidateResponse,
    MessageResponse,
)
from app.services.dataset_service import DatasetGroupService

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("", response_model=list[DatasetResponse])
async def list_datasets(
    group_id: str | None = Query(default=None),
    split: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Dataset 목록 조회. 소프트 삭제된 데이터셋은 제외."""
    logger.info("데이터셋 목록 조회", group_id=group_id, split=split, status=status)
    query = select(Dataset).where(Dataset.deleted_at.is_(None))
    if group_id:
        query = query.where(Dataset.group_id == group_id)
    if split:
        query = query.where(Dataset.split == split.upper())
    if status:
        query = query.where(Dataset.status == status.upper())
    query = query.order_by(Dataset.created_at.desc())
    result = await db.execute(query)
    datasets = list(result.scalars().all())
    logger.info("데이터셋 목록 조회 완료", count=len(datasets))
    return datasets


@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Dataset 단건 조회."""
    logger.info("데이터셋 상세 조회", dataset_id=dataset_id)
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        logger.warning("데이터셋 조회 실패", dataset_id=dataset_id)
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@router.patch("/{dataset_id}", response_model=DatasetResponse)
async def update_dataset(
    dataset_id: str,
    data: DatasetUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Dataset 개별 수정 (annotation_format 등)."""
    logger.info("데이터셋 수정 요청", dataset_id=dataset_id, data=data.model_dump(exclude_unset=True))
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    updated = await svc.update_dataset(dataset, data)
    logger.info("데이터셋 수정 완료", dataset_id=dataset_id)
    return updated


@router.put("/{dataset_id}/meta-file", response_model=DatasetResponse)
async def replace_meta_file(
    dataset_id: str,
    req: DatasetMetaFileReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    """어노테이션 메타 파일 교체 (업로드 경로에서 관리 스토리지로 복사)."""
    logger.info("메타 파일 교체 요청", dataset_id=dataset_id, source=req.source_annotation_meta_file)
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    try:
        updated = await svc.replace_annotation_meta_file(dataset, req.source_annotation_meta_file)
    except ValueError as replace_error:
        raise HTTPException(status_code=400, detail=str(replace_error))
    logger.info("메타 파일 교체 완료", dataset_id=dataset_id, file=updated.annotation_meta_file)
    return updated


@router.post("/{dataset_id}/validate", response_model=FormatValidateResponse)
async def validate_dataset(
    dataset_id: str,
    req: DatasetValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    이미 등록된 데이터셋의 어노테이션 검증 + 클래스 정보 DB 저장.

    관리 스토리지에 저장된 파일을 읽어 검증하고,
    성공 시 class_count, metadata(class_mapping)를 업데이트.
    """
    logger.info("데이터셋 검증 요청", dataset_id=dataset_id, annotation_format=req.annotation_format)
    svc = DatasetGroupService(db)
    try:
        result = await svc.validate_and_persist_class_info(dataset_id, req.annotation_format)
    except ValueError as validation_error:
        raise HTTPException(status_code=400, detail=str(validation_error))
    logger.info("데이터셋 검증 완료", dataset_id=dataset_id, valid=result.valid)
    return result


@router.delete("/{dataset_id}", response_model=MessageResponse)
async def delete_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Dataset 소프트 삭제. 버전 이력은 보존된다."""
    logger.info("데이터셋 삭제 요청", dataset_id=dataset_id)
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    await svc.delete_dataset(dataset)
    logger.info(
        "데이터셋 소프트 삭제 완료",
        dataset_id=dataset_id,
        split=dataset.split,
        version=dataset.version,
    )
    return MessageResponse(message=f"Dataset {dataset.split}/{dataset.version} 삭제 완료")
