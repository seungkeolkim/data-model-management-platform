"""
DatasetGroup 비즈니스 로직 서비스
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
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
    # NAS 경로 + COCO 검증
    # -------------------------------------------------------------------------

    def validate_storage_uri(self, storage_uri: str) -> DatasetValidateResponse:
        """NAS 경로 구조 + COCO annotation 유효성 검사."""
        base = Path(settings.local_storage_base)
        full_path = base / storage_uri

        path_exists = full_path.exists()
        images_dir = full_path / "images"
        images_dir_exists = images_dir.exists()

        # annotation.json 경로 탐색
        annotation_path = full_path / "annotation.json"
        annotation_exists = annotation_path.exists()

        # 이미지 수 카운트
        image_count = 0
        if images_dir_exists:
            image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
            image_count = sum(
                1 for f in images_dir.iterdir()
                if f.is_file() and f.suffix.lower() in image_extensions
            )

        # COCO annotation 검증
        coco_valid = False
        coco_categories: list[str] = []
        coco_annotation_count = 0
        error = None

        if annotation_exists:
            coco_result = self._validate_coco_annotation(annotation_path)
            coco_valid = coco_result["valid"]
            coco_categories = coco_result.get("categories", [])
            coco_annotation_count = coco_result.get("annotation_count", 0)
            error = coco_result.get("error")

        return DatasetValidateResponse(
            storage_uri=storage_uri,
            path_exists=path_exists,
            images_dir_exists=images_dir_exists,
            annotation_exists=annotation_exists,
            image_count=image_count,
            coco_valid=coco_valid,
            coco_categories=coco_categories,
            coco_annotation_count=coco_annotation_count,
            error=error,
        )

    def _validate_coco_annotation(self, annotation_path: Path) -> dict[str, Any]:
        """
        COCO annotation.json 구조 검증.
        필수 키: images, annotations, categories
        """
        try:
            with open(annotation_path, encoding="utf-8") as f:
                data = json.load(f)

            missing = [k for k in ("images", "annotations", "categories") if k not in data]
            if missing:
                return {
                    "valid": False,
                    "error": f"COCO 필수 키 누락: {missing}",
                }

            categories = [cat.get("name", "") for cat in data["categories"]]
            annotation_count = len(data["annotations"])

            return {
                "valid": True,
                "categories": categories,
                "annotation_count": annotation_count,
            }
        except json.JSONDecodeError as e:
            return {"valid": False, "error": f"JSON 파싱 오류: {e}"}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # GUI 등록 (NAS 경로 지정 방식)
    # -------------------------------------------------------------------------

    async def register_dataset(self, req: DatasetRegisterRequest) -> tuple[DatasetGroup, Dataset]:
        """
        GUI Dataset 등록.
        1. NAS 경로 검증 (경로 존재 + COCO annotation 유효성)
        2. DatasetGroup 신규 생성 또는 기존 그룹에 추가
        3. Dataset(split/version) DB 저장
        """
        # NAS 경로 검증
        validation = self.validate_storage_uri(req.storage_uri)

        if not validation.path_exists:
            raise ValueError(
                f"경로가 존재하지 않습니다: {req.storage_uri}\n"
                f"NAS 마운트 기준 경로를 확인하세요. (기준: {settings.local_storage_base})"
            )
        if not validation.images_dir_exists:
            raise ValueError(
                f"images 디렉토리가 없습니다: {req.storage_uri}/images\n"
                f"이미지를 images/ 폴더에 배치한 후 다시 시도하세요."
            )
        if not validation.annotation_exists:
            raise ValueError(
                f"annotation.json 파일이 없습니다: {req.storage_uri}/annotation.json\n"
                f"COCO 형식의 annotation.json 파일을 배치한 후 다시 시도하세요."
            )
        if not validation.coco_valid:
            raise ValueError(
                f"COCO annotation 검증 실패: {validation.error}"
            )

        # 그룹 처리
        if req.group_id:
            result = await self.db.execute(
                select(DatasetGroup).where(DatasetGroup.id == req.group_id)
            )
            group = result.scalar_one_or_none()
            if not group:
                raise ValueError(f"DatasetGroup을 찾을 수 없습니다: {req.group_id}")
        else:
            # 동일 이름 그룹 중복 체크
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
                dataset_type=req.dataset_type,
                annotation_format=req.annotation_format,
                task_types=req.task_types,
                modality=req.modality,
                source_origin=req.source_origin,
                description=req.description,
            )
            self.db.add(group)
            await self.db.flush()

        # 동일 group+split+version 중복 체크
        version = req.version or await self._next_version(group.id, req.split)
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

        # Dataset 생성
        dataset = Dataset(
            id=str(uuid.uuid4()),
            group_id=group.id,
            split=req.split.upper(),
            version=version,
            annotation_format=req.annotation_format,
            storage_uri=req.storage_uri,
            status="READY",
            image_count=validation.image_count,
            class_count=len(validation.coco_categories),
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

        try:
            parts = last_version.lstrip("v").split(".")
            patch = int(parts[2]) + 1
            return f"v{parts[0]}.{parts[1]}.{patch}"
        except (IndexError, ValueError):
            return "v1.0.0"
