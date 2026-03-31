"""
DatasetGroup 비즈니스 로직 서비스
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.storage import get_storage_client
from app.models.all_models import Dataset, DatasetGroup
from app.schemas.dataset import (
    DatasetGroupCreate,
    DatasetGroupUpdate,
    DatasetRegisterRequest,
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

        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

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
    # GUI 등록 (파일 브라우저 방식)
    # -------------------------------------------------------------------------

    async def register_dataset(self, req: DatasetRegisterRequest) -> tuple[DatasetGroup, Dataset]:
        """
        GUI Dataset 등록 (파일 브라우저 방식).

        1. source_image_dir, source_annotation_files 경로 검증
        2. DatasetGroup 신규 생성 또는 기존 그룹에 추가
        3. 버전 자동 생성
        4. 관리 스토리지로 파일 복사
        5. Dataset DB 저장

        원본 파일은 복사(copy)하며 삭제하지 않음.
        """
        # ------------------------------------------------------------------
        # 소스 경로 검증
        # ------------------------------------------------------------------
        image_dir = self._validate_browse_path(req.source_image_dir, expect_dir=True)
        annotation_paths = [
            self._validate_browse_path(p, expect_dir=False)
            for p in req.source_annotation_files
        ]

        # 어노테이션 파일명 중복 검사
        filenames = [p.name for p in annotation_paths]
        if len(filenames) != len(set(filenames)):
            raise ValueError("어노테이션 파일명이 중복됩니다. 파일명이 다른 파일을 선택하세요.")

        # ------------------------------------------------------------------
        # 그룹 처리
        # ------------------------------------------------------------------
        if req.group_id:
            result = await self.db.execute(
                select(DatasetGroup).where(DatasetGroup.id == req.group_id)
            )
            group = result.scalar_one_or_none()
            if not group:
                raise ValueError(f"DatasetGroup을 찾을 수 없습니다: {req.group_id}")
        else:
            existing = await self.db.execute(
                select(DatasetGroup).where(DatasetGroup.name == req.group_name)
            )
            if existing.scalar_one_or_none():
                raise ValueError(
                    f"동일한 이름의 데이터셋 그룹이 이미 존재합니다: '{req.group_name}'\n"
                    f"기존 그룹에 추가하려면 group_id를 지정하세요."
                )
            group = DatasetGroup(
                id=str(uuid.uuid4()),
                name=req.group_name,
                dataset_type="RAW",
                annotation_format=req.annotation_format,
                task_types=req.task_types,
                modality=req.modality,
                source_origin=req.source_origin,
                description=req.description,
            )
            self.db.add(group)
            await self.db.flush()

        # ------------------------------------------------------------------
        # 버전 자동 생성
        # ------------------------------------------------------------------
        version = await self._next_version(group.id, req.split)

        dup = await self.db.execute(
            select(Dataset).where(
                Dataset.group_id == group.id,
                Dataset.split == req.split.upper(),
                Dataset.version == version,
            )
        )
        if dup.scalar_one_or_none():
            raise ValueError(
                f"동일한 split/version 데이터셋이 이미 존재합니다: "
                f"split={req.split}, version={version}"
            )

        # ------------------------------------------------------------------
        # storage_uri 결정 및 파일 복사
        # ------------------------------------------------------------------
        group_name = group.name
        storage_uri = self.storage.build_dataset_uri("RAW", group_name, req.split, version)
        dest_abs = Path(settings.local_storage_base) / storage_uri

        try:
            image_count = self.storage.copy_image_directory(image_dir, storage_uri)
            annotation_filenames = self.storage.copy_annotation_files(annotation_paths, storage_uri)
        except Exception as e:
            # 복사 실패 시 부분 생성된 디렉토리 정리
            if dest_abs.exists():
                shutil.rmtree(dest_abs, ignore_errors=True)
            raise ValueError(f"파일 복사 중 오류가 발생했습니다: {e}") from e

        # ------------------------------------------------------------------
        # Dataset DB 저장
        # ------------------------------------------------------------------
        dataset = Dataset(
            id=str(uuid.uuid4()),
            group_id=group.id,
            split=req.split.upper(),
            version=version,
            annotation_format=req.annotation_format,
            storage_uri=storage_uri,
            status="READY",
            image_count=image_count,
            class_count=None,
            annotation_files=annotation_filenames,
        )
        self.db.add(dataset)
        await self.db.flush()

        return group, dataset

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _validate_browse_path(self, path_str: str, expect_dir: bool) -> Path:
        """
        경로 존재 여부 및 타입 확인.
        docker-compose에서 LOCAL_UPLOAD_BASE만 마운트하므로 별도 경로 제한 불필요.
        expect_dir=True이면 디렉토리, False이면 파일이어야 함.
        """
        p = Path(path_str)

        if not p.exists():
            raise ValueError(f"경로가 존재하지 않습니다: {path_str}")

        if expect_dir and not p.is_dir():
            raise ValueError(f"디렉토리가 아닙니다: {path_str}")

        if not expect_dir and not p.is_file():
            raise ValueError(f"파일이 아닙니다: {path_str}")

        return p

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

        try:
            parts = last_version.lstrip("v").split(".")
            patch = int(parts[2]) + 1
            return f"v{parts[0]}.{parts[1]}.{patch}"
        except (IndexError, ValueError):
            return "v1.0.0"
