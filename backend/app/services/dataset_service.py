"""
DatasetGroup 비즈니스 로직 서비스
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.storage import get_storage_client
from app.models.all_models import Dataset, DatasetGroup, DatasetLineage
from app.schemas.dataset import (
    DatasetGroupCreate,
    DatasetGroupUpdate,
    DatasetRegisterRequest,
    DatasetValidateResponse,
)


class DatasetGroupService:
    """DatasetGroup CRUD + 비즈니스 로직."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = get_storage_client()

    # -------------------------------------------------------------------------
    # 목록 조회
    # -------------------------------------------------------------------------

    async def list_groups(
        self,
        page: int = 1,
        page_size: int = 20,
        dataset_type: str | None = None,
        search: str | None = None,
    ) -> tuple[list[DatasetGroup], int]:
        """데이터셋 그룹 목록 조회 (페이지네이션)."""
        query = select(DatasetGroup).options(selectinload(DatasetGroup.datasets))

        if dataset_type:
            query = query.where(DatasetGroup.dataset_type == dataset_type.upper())
        if search:
            query = query.where(DatasetGroup.name.ilike(f"%{search}%"))

        # 전체 카운트
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        # 페이지 적용
        query = query.offset((page - 1) * page_size).limit(page_size)
        query = query.order_by(DatasetGroup.updated_at.desc())

        result = await self.db.execute(query)
        groups = list(result.scalars().all())
        return groups, total

    # -------------------------------------------------------------------------
    # 단건 조회
    # -------------------------------------------------------------------------

    async def get_group(self, group_id: str) -> DatasetGroup | None:
        """단건 DatasetGroup 조회 (datasets 포함)."""
        result = await self.db.execute(
            select(DatasetGroup)
            .where(DatasetGroup.id == group_id)
            .options(selectinload(DatasetGroup.datasets))
        )
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # 생성
    # -------------------------------------------------------------------------

    async def create_group(self, data: DatasetGroupCreate) -> DatasetGroup:
        """DatasetGroup 생성."""
        group = DatasetGroup(
            id=str(uuid.uuid4()),
            **data.model_dump(),
        )
        self.db.add(group)
        await self.db.flush()
        await self.db.refresh(group, ["datasets"])
        return group

    # -------------------------------------------------------------------------
    # 수정
    # -------------------------------------------------------------------------

    async def update_group(self, group: DatasetGroup, data: DatasetGroupUpdate) -> DatasetGroup:
        """DatasetGroup 수정."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(group, field, value)
        await self.db.flush()
        await self.db.refresh(group)
        return group

    # -------------------------------------------------------------------------
    # 삭제
    # -------------------------------------------------------------------------

    async def delete_group(self, group: DatasetGroup) -> None:
        """DatasetGroup 삭제 (CASCADE: datasets, lineage 함께 삭제)."""
        await self.db.delete(group)
        await self.db.flush()

    # -------------------------------------------------------------------------
    # NAS 경로 검증
    # -------------------------------------------------------------------------

    def validate_storage_uri(self, storage_uri: str) -> DatasetValidateResponse:
        """NAS 경로 구조 유효성 검사."""
        result = self.storage.validate_structure(storage_uri)
        return DatasetValidateResponse(
            storage_uri=storage_uri,
            **result,
        )

    # -------------------------------------------------------------------------
    # GUI 등록 (NAS 경로 지정 방식)
    # -------------------------------------------------------------------------

    async def register_dataset(self, req: DatasetRegisterRequest) -> tuple[DatasetGroup, Dataset]:
        """
        GUI Dataset 등록.
        - 새 그룹 또는 기존 그룹에 Dataset(split/version) 추가
        - NAS 경로 검증 후 DB 저장
        """
        # 그룹 처리
        if req.group_id:
            result = await self.db.execute(
                select(DatasetGroup).where(DatasetGroup.id == req.group_id)
            )
            group = result.scalar_one_or_none()
            if not group:
                raise ValueError(f"DatasetGroup not found: {req.group_id}")
        else:
            if not req.group_name:
                raise ValueError("group_id 또는 group_name 중 하나는 필수입니다.")
            group = DatasetGroup(
                id=str(uuid.uuid4()),
                name=req.group_name,
                dataset_type=req.dataset_type,
                annotation_format=req.annotation_format,
                task_types=req.task_types,
                modality=req.modality,
                source_origin=req.source_origin,
                description=req.description,
            )
            self.db.add(group)
            await self.db.flush()

        # 버전 자동 생성
        version = req.version or await self._next_version(group.id, req.split)

        # 이미지 수 카운트 (경로가 존재하는 경우)
        image_count = None
        if self.storage.exists(req.storage_uri):
            try:
                from app.core.storage import LocalStorageClient
                if isinstance(self.storage, LocalStorageClient):
                    image_count = self.storage.count_images(req.storage_uri)
            except Exception:
                pass

        # Dataset 생성
        dataset = Dataset(
            id=str(uuid.uuid4()),
            group_id=group.id,
            split=req.split.upper(),
            version=version,
            annotation_format=req.annotation_format,
            storage_uri=req.storage_uri,
            status="READY" if self.storage.exists(req.storage_uri) else "PENDING",
            image_count=image_count,
        )
        self.db.add(dataset)
        await self.db.flush()

        return group, dataset

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def _next_version(self, group_id: str, split: str) -> str:
        """해당 group+split 의 다음 버전 자동 계산."""
        result = await self.db.execute(
            select(Dataset.version)
            .where(Dataset.group_id == group_id, Dataset.split == split.upper())
            .order_by(Dataset.created_at.desc())
            .limit(1)
        )
        last_version = result.scalar_one_or_none()
        if not last_version:
            return "v1.0.0"

        # v1.0.0 → v1.0.1
        try:
            parts = last_version.lstrip("v").split(".")
            patch = int(parts[2]) + 1
            return f"v{parts[0]}.{parts[1]}.{patch}"
        except (IndexError, ValueError):
            return "v1.0.0"
