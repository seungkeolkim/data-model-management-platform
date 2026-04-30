"""
DatasetGroup 비즈니스 로직 서비스
"""
from __future__ import annotations

import json
import random
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import structlog
from sqlalchemy import Text, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import app_config, settings
from app.core.storage import get_storage_client
from app.models.all_models import DatasetGroup, DatasetSplit, DatasetVersion
from app.schemas.dataset import (
    ClassificationHeadWarning,
    DatasetGroupCreate,
    DatasetGroupUpdate,
    DatasetRegisterClassificationRequest,
    DatasetRegisterRequest,
    DatasetUpdate,
    FormatValidateRequest,
    FormatValidateResponse,
)

logger = structlog.get_logger(__name__)


class DatasetGroupService:
    """DatasetGroup CRUD + 비즈니스 로직."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = get_storage_client()

    # -------------------------------------------------------------------------
    # 목록 조회
    # -------------------------------------------------------------------------

    # 정렬 가능한 컬럼 화이트리스트. 프론트에서 전달된 sort_by 값을 이 사전에서만 받는다.
    # dataset_count / total_image_count 는 활성 Dataset 기준 집계값이며
    # list_groups 내부에서 LEFT JOIN 되는 서브쿼리 컬럼을 런타임에 매핑한다.
    _SORTABLE_COLUMN_KEYS: tuple[str, ...] = (
        "name",
        "dataset_type",
        "task_types",
        "annotation_format",
        "created_at",
        "updated_at",
        "dataset_count",
        "total_image_count",
    )

    async def list_groups(
        self,
        page: int = 1,
        page_size: int = 20,
        dataset_type: list[str] | None = None,
        task_type: list[str] | None = None,
        annotation_format: list[str] | None = None,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> tuple[list[DatasetGroup], int]:
        """
        데이터셋 그룹 목록 조회 (페이지네이션 + 필터 + 정렬).

        필터(전부 다중 선택 가능, 각 필터 내부는 OR / 서로 다른 필터 간은 AND):
          - dataset_type: RAW / SOURCE / PROCESSED / FUSION 중 복수
          - task_type: DETECTION / CLASSIFICATION / SEGMENTATION / ZERO_SHOT 중 복수
            (DatasetGroup.task_types JSONB 배열이 해당 값들 중 하나라도 포함하는지 검사)
          - annotation_format: COCO / YOLO / CLS_MANIFEST 등 중 복수
          - search: 그룹명 부분일치 (ilike)

        정렬:
          - sort_by: _SORTABLE_COLUMN_KEYS 중 하나 (미지정/비허용값이면 updated_at 강제)
          - sort_order: "asc" | "desc" (그 외 값이면 desc 강제)
          - dataset_count / total_image_count 는 활성 Dataset 기준 집계.
            원본 Dataset.image_count 가 NULL 이면 0 으로 간주.

        소프트 삭제된 그룹은 항상 제외한다.
        """
        # 활성 DatasetVersion 집계 서브쿼리.
        # v7.9 (3계층 분리): DatasetSplit 을 경유해 group_id 를 얻고, 활성 버전만 집계.
        datasets_aggregate_subquery = (
            select(
                DatasetSplit.group_id.label("group_id"),
                func.count(DatasetVersion.id).label("dataset_count"),
                func.coalesce(
                    func.sum(DatasetVersion.image_count), 0
                ).label("total_image_count"),
            )
            .join(DatasetSplit, DatasetVersion.split_id == DatasetSplit.id)
            .where(DatasetVersion.deleted_at.is_(None))
            .group_by(DatasetSplit.group_id)
            .subquery()
        )

        base_query = (
            select(DatasetGroup)
            .outerjoin(
                datasets_aggregate_subquery,
                datasets_aggregate_subquery.c.group_id == DatasetGroup.id,
            )
            .where(DatasetGroup.deleted_at.is_(None))
            .options(
                # group.splits → split.versions (활성만) → version.pipeline_runs
                selectinload(DatasetGroup.splits)
                .selectinload(
                    DatasetSplit.versions.and_(DatasetVersion.deleted_at.is_(None))
                )
                .selectinload(DatasetVersion.pipeline_runs)
            )
        )

        if dataset_type:
            normalized_dataset_types = [value.upper() for value in dataset_type]
            base_query = base_query.where(
                DatasetGroup.dataset_type.in_(normalized_dataset_types)
            )
        if annotation_format:
            normalized_annotation_formats = [value.upper() for value in annotation_format]
            base_query = base_query.where(
                DatasetGroup.annotation_format.in_(normalized_annotation_formats)
            )
        if task_type:
            # task_types 는 JSONB 배열. ["DETECTION"] 형태로 저장되므로
            # 선택된 값 각각에 대해 JSONB @> contains 를 만들고 OR 로 합친다.
            # (예: task_type=[DETECTION,CLASSIFICATION] → 둘 중 하나라도 포함)
            normalized_task_types = [value.upper() for value in task_type]
            task_type_clauses = [
                DatasetGroup.task_types.contains([value])
                for value in normalized_task_types
            ]
            base_query = base_query.where(or_(*task_type_clauses))
        if search:
            base_query = base_query.where(DatasetGroup.name.ilike(f"%{search}%"))

        # 정렬 컬럼 매핑 — 화이트리스트 밖의 값이 들어오면 updated_at 로 폴백.
        sortable_column_map = {
            "name": DatasetGroup.name,
            "dataset_type": DatasetGroup.dataset_type,
            # task_types 는 JSONB 배열. 일반 연산자로는 정렬이 불가하므로
            # text 로 캐스팅한 값(예: '["DETECTION"]')을 사전식으로 정렬한다.
            # CLAUDE.md 규약상 원소 1개짜리 배열이므로 실질적으로 task type
            # 이름순 정렬과 같아진다.
            "task_types": func.cast(DatasetGroup.task_types, Text),
            "annotation_format": DatasetGroup.annotation_format,
            "created_at": DatasetGroup.created_at,
            "updated_at": DatasetGroup.updated_at,
            "dataset_count": func.coalesce(
                datasets_aggregate_subquery.c.dataset_count, 0
            ),
            "total_image_count": func.coalesce(
                datasets_aggregate_subquery.c.total_image_count, 0
            ),
        }
        sort_column_expression = sortable_column_map.get(
            sort_by, DatasetGroup.updated_at
        )
        if sort_order.lower() == "asc":
            primary_order = sort_column_expression.asc()
        else:
            primary_order = sort_column_expression.desc()
        # 동률일 때 재현 가능한 순서를 위해 id 를 보조 정렬 키로 둔다.
        secondary_order = DatasetGroup.id.asc()

        # count 는 필터만 반영하고 정렬/페이지네이션 없이 계산.
        count_query = select(func.count()).select_from(
            base_query.order_by(None).subquery()
        )
        total = await self.db.scalar(count_query) or 0

        paginated_query = (
            base_query.order_by(primary_order, secondary_order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        result = await self.db.execute(paginated_query)
        groups = list(result.scalars().unique().all())
        return groups, total

    # -------------------------------------------------------------------------
    # 단건 조회
    # -------------------------------------------------------------------------

    async def get_group(self, group_id: str) -> DatasetGroup | None:
        """단건 DatasetGroup 조회 (splits + versions + pipeline_runs 포함). 소프트 삭제된 그룹은 제외."""
        result = await self.db.execute(
            select(DatasetGroup)
            .where(DatasetGroup.id == group_id, DatasetGroup.deleted_at.is_(None))
            .options(
                selectinload(DatasetGroup.splits)
                .selectinload(
                    DatasetSplit.versions.and_(DatasetVersion.deleted_at.is_(None))
                )
                .selectinload(DatasetVersion.pipeline_runs)
            )
        )
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # 생성
    # -------------------------------------------------------------------------

    async def create_group(self, data: DatasetGroupCreate) -> DatasetGroup:
        """DatasetGroup 생성. 활성 그룹 중 동일 이름이 있으면 거부."""
        existing = await self.db.execute(
            select(DatasetGroup).where(
                DatasetGroup.name == data.name,
                DatasetGroup.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"동일한 이름의 데이터셋 그룹이 이미 존재합니다: '{data.name}'")

        group = DatasetGroup(
            id=str(uuid.uuid4()),
            **data.model_dump(),
        )
        self.db.add(group)
        await self.db.flush()
        # datasets 는 association_proxy 이므로 refresh 로 바로 채울 수 없다.
        # splits 관계만 명시적으로 갱신하면 association_proxy 가 동작한다.
        await self.db.refresh(group, ["splits"])
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

    async def delete_group(self, group: DatasetGroup) -> int:
        """
        DatasetGroup 소프트 삭제.
        하위 활성 데이터셋(DatasetVersion)의 스토리지 파일을 먼저 삭제한 뒤 DB를 소프트 삭제한다.
        삭제된 레코드의 버전 이력은 보존되어 다음 버전 자동 계산에 반영된다.
        반환값: 함께 삭제된 DatasetVersion 수.
        """
        # 하위 활성 DatasetVersion 의 스토리지 파일 삭제 (split 경유 JOIN)
        active_versions_result = await self.db.execute(
            select(DatasetVersion)
            .join(DatasetSplit, DatasetVersion.split_id == DatasetSplit.id)
            .where(
                DatasetSplit.group_id == group.id,
                DatasetVersion.deleted_at.is_(None),
            )
        )
        active_versions = list(active_versions_result.scalars().all())

        for dataset in active_versions:
            self._delete_dataset_storage(dataset.storage_uri)

        # DB 소프트 삭제
        now = datetime.utcnow()
        group.deleted_at = now

        # Bulk update — split 경유 subquery 로 대상 id 수집.
        # 이 경로는 ORM 이벤트를 트리거하지 않지만, group 자체가 ORM 경로로
        # 수정되므로 group.updated_at 은 onupdate 로 자연스럽게 갱신된다.
        target_version_ids_subquery = (
            select(DatasetVersion.id)
            .join(DatasetSplit, DatasetVersion.split_id == DatasetSplit.id)
            .where(
                DatasetSplit.group_id == group.id,
                DatasetVersion.deleted_at.is_(None),
            )
            .scalar_subquery()
        )
        await self.db.execute(
            update(DatasetVersion)
            .where(DatasetVersion.id.in_(target_version_ids_subquery))
            .values(deleted_at=now)
        )
        await self.db.flush()
        return len(active_versions)

    async def delete_dataset(self, dataset: Dataset) -> None:
        """
        Dataset 개별 소프트 삭제.
        스토리지 파일을 먼저 삭제한 뒤 DB를 소프트 삭제한다.
        삭제된 레코드의 버전 이력은 보존되어 다음 버전 자동 계산에 반영된다.
        """
        self._delete_dataset_storage(dataset.storage_uri)
        dataset.deleted_at = datetime.utcnow()
        await self.db.flush()

    def _delete_dataset_storage(self, storage_uri: str) -> None:
        """데이터셋의 스토리지 디렉토리 삭제. 실패해도 예외를 전파하지 않는다."""
        try:
            self.storage.delete_dataset_directory(storage_uri)
        except Exception as storage_error:
            logger.error(
                "스토리지 파일 삭제 실패 (DB 삭제는 계속 진행)",
                storage_uri=storage_uri,
                error=str(storage_error),
            )

    # -------------------------------------------------------------------------
    # Split 슬롯 조회/생성 헬퍼 (v7.9 3계층 분리)
    # -------------------------------------------------------------------------

    async def _get_or_create_split(
        self, group_id: str, split: str,
    ) -> DatasetSplit:
        """
        (group_id, split) 정적 슬롯을 가져오거나 없으면 생성한다.

        split 은 DatasetGroup 내에서 유일하며, 동일 (group_id, split) 의 재호출은
        항상 같은 DatasetSplit 행을 반환한다. 이 호출이 flush 를 트리거하므로
        caller 가 별도 flush 를 부를 필요는 없다.
        """
        split_upper = split.upper()
        existing = await self.db.execute(
            select(DatasetSplit).where(
                DatasetSplit.group_id == group_id,
                DatasetSplit.split == split_upper,
            )
        )
        split_obj = existing.scalar_one_or_none()
        if split_obj is not None:
            return split_obj

        split_obj = DatasetSplit(
            id=str(uuid.uuid4()),
            group_id=group_id,
            split=split_upper,
        )
        self.db.add(split_obj)
        await self.db.flush()
        return split_obj

    # -------------------------------------------------------------------------
    # Classification 등록
    # -------------------------------------------------------------------------

    async def register_classification_dataset(
        self,
        req: DatasetRegisterClassificationRequest,
    ) -> tuple[DatasetGroup, Dataset, str | None, list[ClassificationHeadWarning]]:
        """
        Classification 전용 RAW 데이터셋 등록.

        - source_root_dir은 LOCAL_UPLOAD_BASE 하위여야 하고 존재하는 디렉토리
        - source_class_paths(각 head의 class 경로)는 존재 자체만 확인 (빈 dir 허용)
        - 기존 그룹이면 head_schema 일관성 검증 후 경고/차단
        - 신규 그룹이면 head_schema를 새로 기록, annotation_format=CLS_MANIFEST 고정
        - Dataset 선생성(PROCESSING) + Celery 태스크 dispatch
        """
        from app.tasks.register_classification_tasks import (
            register_classification_dataset as register_classification_task,
        )

        # ------------------------------------------------------------------
        # 소스 경로 검증
        # ------------------------------------------------------------------
        logger.info(
            "Classification 등록 요청",
            root_dir=req.source_root_dir,
            heads=[head.name for head in req.heads],
        )
        root_dir = self._validate_browse_path(req.source_root_dir, expect_dir=True)
        # LOCAL_UPLOAD_BASE 하위인지 확인 (파일 브라우저 라우터와 동일한 정책)
        upload_base = Path(settings.local_upload_base)
        try:
            root_dir.relative_to(upload_base)
        except ValueError as exc:
            raise ValueError(
                f"허용된 업로드 루트({upload_base}) 하위 경로만 등록할 수 있습니다: {root_dir}"
            ) from exc

        # head별 class 경로 존재 검증 (빈 dir 허용)
        for head in req.heads:
            for class_path_str in head.source_class_paths:
                class_path = Path(class_path_str)
                if not class_path.exists():
                    raise ValueError(
                        f"class 경로가 존재하지 않습니다 (head={head.name}): {class_path_str}"
                    )
                if not class_path.is_dir():
                    raise ValueError(
                        f"class 경로가 디렉토리가 아닙니다 (head={head.name}): {class_path_str}"
                    )

        # ------------------------------------------------------------------
        # 그룹 처리 + head_schema 일관성 검증
        # ------------------------------------------------------------------
        warnings: list[ClassificationHeadWarning] = []
        new_head_schema = {
            "heads": [
                {
                    "name": head.name,
                    "multi_label": head.multi_label,
                    "classes": list(head.classes),
                }
                for head in req.heads
            ]
        }

        if req.group_id:
            result = await self.db.execute(
                select(DatasetGroup).where(DatasetGroup.id == req.group_id)
            )
            group = result.scalar_one_or_none()
            if not group:
                raise ValueError(f"DatasetGroup을 찾을 수 없습니다: {req.group_id}")
            if not (group.task_types and "CLASSIFICATION" in group.task_types):
                raise ValueError(
                    "지정한 그룹은 CLASSIFICATION 용도가 아닙니다. 다른 그룹을 선택하세요."
                )
            existing_schema = group.head_schema or {"heads": []}
            # 단일 원칙 (설계서 §2-8): schema 가 달라지면 ValueError 로 차단.
            # 통과 = 기존과 동일 → group.head_schema 는 건드리지 않는다.
            warnings = _diff_head_schema(existing_schema, new_head_schema)
        else:
            existing = await self.db.execute(
                select(DatasetGroup).where(
                    DatasetGroup.name == req.group_name,
                    DatasetGroup.deleted_at.is_(None),
                )
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
                annotation_format="CLS_MANIFEST",
                task_types=["CLASSIFICATION"],
                modality=req.modality,
                source_origin=req.source_origin,
                description=req.description,
                head_schema=new_head_schema,
            )
            self.db.add(group)
            await self.db.flush()

        # ------------------------------------------------------------------
        # Split 슬롯 선조회/생성 → 버전 계산 → DatasetVersion 선생성
        # ------------------------------------------------------------------
        split_obj = await self._get_or_create_split(group.id, req.split)
        version = await self._next_version(split_obj.id)
        dup = await self.db.execute(
            select(DatasetVersion).where(
                DatasetVersion.split_id == split_obj.id,
                DatasetVersion.version == version,
                DatasetVersion.deleted_at.is_(None),
            )
        )
        if dup.scalar_one_or_none():
            raise ValueError(
                f"동일한 split/version 데이터셋이 이미 존재합니다: "
                f"split={req.split}, version={version}"
            )

        storage_uri = self.storage.build_dataset_uri(
            "RAW", group.name, req.split, version,
        )
        dataset = DatasetVersion(
            id=str(uuid.uuid4()),
            split_id=split_obj.id,
            version=version,
            annotation_format="CLS_MANIFEST",
            storage_uri=storage_uri,
            status="PROCESSING",
        )
        self.db.add(dataset)
        await self.db.flush()

        # ------------------------------------------------------------------
        # Celery 태스크 dispatch
        # ------------------------------------------------------------------
        heads_payload = [
            {
                "name": head.name,
                "multi_label": head.multi_label,
                "classes": list(head.classes),
                "source_class_paths": list(head.source_class_paths),
            }
            for head in req.heads
        ]
        async_result = register_classification_task.delay(
            dataset_id=dataset.id,
            storage_uri=storage_uri,
            heads_payload=heads_payload,
        )
        logger.info(
            "Classification 등록 태스크 dispatch 완료",
            dataset_id=dataset.id,
            celery_task_id=async_result.id,
        )

        return group, dataset, async_result.id, warnings

    # -------------------------------------------------------------------------
    # GUI 등록 (파일 브라우저 방식)
    # -------------------------------------------------------------------------

    async def register_dataset(self, req: DatasetRegisterRequest) -> tuple[DatasetGroup, Dataset]:
        """
        GUI Dataset 등록 (파일 브라우저 방식).

        1. source_image_dir, source_annotation_files 경로 검증
        2. DatasetGroup 신규 생성 또는 기존 그룹에 추가
        3. 버전 자동 생성
        4. Dataset DB 즉시 저장 (status=PROCESSING)
        5. Celery 태스크로 파일 복사 dispatch

        원본 파일은 복사(copy)하며 삭제하지 않음.
        파일 복사는 Celery worker에서 비동기로 수행된다.
        """
        from app.tasks.register_tasks import register_dataset as register_dataset_task

        # ------------------------------------------------------------------
        # 소스 경로 검증
        # ------------------------------------------------------------------
        logger.info("소스 경로 검증 시작", image_dir=req.source_image_dir, annotation_count=len(req.source_annotation_files))
        image_dir = self._validate_browse_path(req.source_image_dir, expect_dir=True)
        annotation_paths = [
            self._validate_browse_path(p, expect_dir=False)
            for p in req.source_annotation_files
        ]
        # 어노테이션 메타 파일 경로 검증 (선택사항)
        annotation_meta_path: Path | None = None
        if req.source_annotation_meta_file:
            annotation_meta_path = self._validate_browse_path(
                req.source_annotation_meta_file, expect_dir=False
            )
        logger.info("소스 경로 검증 완료")

        # 어노테이션 파일명 중복 검사
        filenames = [p.name for p in annotation_paths]
        if len(filenames) != len(set(filenames)):
            raise ValueError("어노테이션 파일명이 중복됩니다. 파일명이 다른 파일을 선택하세요.")

        # ------------------------------------------------------------------
        # 그룹 처리
        # ------------------------------------------------------------------
        if req.group_id:
            logger.info("기존 그룹에 추가", group_id=req.group_id)
            result = await self.db.execute(
                select(DatasetGroup).where(DatasetGroup.id == req.group_id)
            )
            group = result.scalar_one_or_none()
            if not group:
                raise ValueError(f"DatasetGroup을 찾을 수 없습니다: {req.group_id}")
            logger.info("기존 그룹 확인됨", group_name=group.name)
        else:
            existing = await self.db.execute(
                select(DatasetGroup).where(
                    DatasetGroup.name == req.group_name,
                    DatasetGroup.deleted_at.is_(None),
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError(
                    f"동일한 이름의 데이터셋 그룹이 이미 존재합니다: '{req.group_name}'\n"
                    f"기존 그룹에 추가하려면 group_id를 지정하세요."
                )
            logger.info("신규 그룹 생성", group_name=req.group_name)
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
            logger.info("신규 그룹 DB 저장 완료", group_id=group.id)

        # ------------------------------------------------------------------
        # Split 슬롯 선조회/생성 → 버전 자동 생성
        # ------------------------------------------------------------------
        split_obj = await self._get_or_create_split(group.id, req.split)
        version = await self._next_version(split_obj.id)
        logger.info("버전 자동 생성", version=version, split=req.split)

        dup = await self.db.execute(
            select(DatasetVersion).where(
                DatasetVersion.split_id == split_obj.id,
                DatasetVersion.version == version,
                DatasetVersion.deleted_at.is_(None),
            )
        )
        if dup.scalar_one_or_none():
            raise ValueError(
                f"동일한 split/version 데이터셋이 이미 존재합니다: "
                f"split={req.split}, version={version}"
            )

        # ------------------------------------------------------------------
        # storage_uri 결정 + DatasetVersion 즉시 생성 (PROCESSING)
        # ------------------------------------------------------------------
        group_name = group.name
        storage_uri = self.storage.build_dataset_uri("RAW", group_name, req.split, version)

        dataset = DatasetVersion(
            id=str(uuid.uuid4()),
            split_id=split_obj.id,
            version=version,
            annotation_format=req.annotation_format,
            storage_uri=storage_uri,
            status="PROCESSING",
            image_count=None,
            class_count=None,
            annotation_files=None,
            annotation_meta_file=None,
        )
        self.db.add(dataset)
        await self.db.flush()
        logger.info("Dataset DB 저장 완료 (PROCESSING)", dataset_id=dataset.id)

        # ------------------------------------------------------------------
        # Celery 태스크 dispatch — 파일 복사는 worker에서 비동기 수행
        # ------------------------------------------------------------------
        register_dataset_task.delay(
            dataset_id=dataset.id,
            storage_uri=storage_uri,
            source_image_dir=str(image_dir),
            source_annotation_files=[str(p) for p in annotation_paths],
            source_annotation_meta_file=str(annotation_meta_path) if annotation_meta_path else None,
            annotation_format=req.annotation_format,
        )
        logger.info("Celery 파일 복사 태스크 dispatch 완료", dataset_id=dataset.id)

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
        validated_path = Path(path_str)

        if not validated_path.exists():
            raise ValueError(f"경로가 존재하지 않습니다: {path_str}")

        if expect_dir and not validated_path.is_dir():
            raise ValueError(f"디렉토리가 아닙니다: {path_str}")

        if not expect_dir and not validated_path.is_file():
            raise ValueError(f"파일이 아닙니다: {path_str}")

        return validated_path

    # -------------------------------------------------------------------------
    # 포맷 검증
    # -------------------------------------------------------------------------

    def validate_annotation_format(self, req: FormatValidateRequest) -> FormatValidateResponse:
        """
        어노테이션 파일이 지정된 포맷에 맞는지 사전 검증.

        COCO: JSON 파싱 → images, annotations, categories 키 존재 + 요약 정보 반환
        YOLO: .txt 파일 → 각 라인이 'class_id x y w h' 형식인지 샘플 검사
        """
        format_name = req.annotation_format.upper()
        if format_name == "COCO":
            return self._validate_coco_format(req.annotation_files)
        elif format_name == "YOLO":
            return self._validate_yolo_format(
                req.annotation_files,
                annotation_meta_file=req.annotation_meta_file,
            )
        else:
            return FormatValidateResponse(
                valid=True,
                errors=[],
                summary={"message": f"{format_name} 포맷은 자동 검증을 지원하지 않습니다."},
            )

    def _validate_coco_format(self, annotation_file_paths: list[str]) -> FormatValidateResponse:
        """
        COCO JSON 포맷 검증.

        각 파일에 대해:
        1. JSON 파싱 가능 여부
        2. 필수 키 (images, annotations, categories) 존재 여부
        3. 데이터 요약 (이미지 수, 어노테이션 수, 카테고리 목록)
        """
        errors: list[str] = []
        total_image_count = 0
        total_annotation_count = 0
        all_category_names: list[str] = []
        file_summaries: list[dict] = []

        required_keys = {"images", "annotations", "categories"}

        for file_path_str in annotation_file_paths:
            file_path = Path(file_path_str)
            filename = file_path.name

            if not file_path.exists():
                errors.append(f"[{filename}] 파일이 존재하지 않습니다: {file_path_str}")
                continue

            if not file_path.suffix.lower() == ".json":
                errors.append(f"[{filename}] COCO 포맷은 .json 파일이어야 합니다.")
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as json_file:
                    data = json.load(json_file)
            except json.JSONDecodeError as json_error:
                errors.append(f"[{filename}] JSON 파싱 실패: {json_error}")
                continue
            except Exception as read_error:
                errors.append(f"[{filename}] 파일 읽기 실패: {read_error}")
                continue

            if not isinstance(data, dict):
                errors.append(f"[{filename}] 최상위 구조가 JSON 객체가 아닙니다.")
                continue

            # 필수 키 확인
            missing_keys = required_keys - set(data.keys())
            if missing_keys:
                errors.append(
                    f"[{filename}] 필수 키가 누락되었습니다: {', '.join(sorted(missing_keys))}"
                )
                continue

            # 타입 확인
            if not isinstance(data["images"], list):
                errors.append(f"[{filename}] 'images'가 배열이 아닙니다.")
                continue
            if not isinstance(data["annotations"], list):
                errors.append(f"[{filename}] 'annotations'가 배열이 아닙니다.")
                continue
            if not isinstance(data["categories"], list):
                errors.append(f"[{filename}] 'categories'가 배열이 아닙니다.")
                continue

            # 요약 정보 수집
            image_count = len(data["images"])
            annotation_count = len(data["annotations"])
            category_names = [
                cat.get("name", f"id={cat.get('id', '?')}")
                for cat in data["categories"]
            ]
            # 클래스 매핑 (id → name) 추출
            category_mapping = {
                str(cat.get("id", "?")): cat.get("name", f"id={cat.get('id', '?')}")
                for cat in data["categories"]
            }

            total_image_count += image_count
            total_annotation_count += annotation_count
            all_category_names.extend(category_names)

            file_summaries.append({
                "filename": filename,
                "image_count": image_count,
                "annotation_count": annotation_count,
                "category_count": len(category_names),
                "categories": category_names,
                "class_mapping": category_mapping,
            })

        is_valid = len(errors) == 0
        summary = None
        if is_valid:
            # 카테고리 중복 제거 (여러 파일에서 동일 카테고리가 나올 수 있음)
            unique_categories = sorted(set(all_category_names))
            # 전체 파일의 class_mapping을 합산 (동일 id면 덮어씀 — 정상적이면 일치)
            merged_class_mapping: dict[str, str] = {}
            for file_summary in file_summaries:
                merged_class_mapping.update(file_summary.get("class_mapping", {}))
            summary = {
                "total_image_count": total_image_count,
                "total_annotation_count": total_annotation_count,
                "total_category_count": len(unique_categories),
                "categories": unique_categories,
                "class_mapping": merged_class_mapping,
                "files": file_summaries,
            }

        return FormatValidateResponse(valid=is_valid, errors=errors, summary=summary)

    def _validate_yolo_format(
        self,
        annotation_file_paths: list[str],
        annotation_meta_file: str | None = None,
    ) -> FormatValidateResponse:
        """
        YOLO txt 포맷 검증.

        파일이 대량(수천~수만)일 경우 전체를 검사하면 과도하므로
        MAX_SAMPLE_FILES개를 랜덤 샘플링하여 검증.
        각 파일에 대해:
        1. .txt 확장자 확인
        2. 샘플 라인이 'class_id center_x center_y width height' 형식인지 확인
        3. 값 범위 확인 (좌표 0~1, class_id 정수)

        annotation_meta_file이 있으면 yaml을 파싱하여 class name 매핑에 활용한다.
        """
        errors: list[str] = []
        total_label_count = 0
        class_id_set: set[int] = set()
        max_sample_lines = 20  # 파일당 샘플 검사 라인 수
        max_sample_files = 50  # 대량 파일 시 검사할 최대 파일 수

        total_file_count = len(annotation_file_paths)
        is_sampled = total_file_count > max_sample_files

        # 대량 파일이면 랜덤 샘플링
        if is_sampled:
            sampled_paths = random.sample(annotation_file_paths, max_sample_files)
        else:
            sampled_paths = annotation_file_paths

        # 전체 파일에서 .txt 확장자 비율 빠르게 확인
        non_txt_count = sum(
            1 for p in annotation_file_paths if not p.lower().endswith(".txt")
        )
        if non_txt_count > 0:
            errors.append(
                f"전체 {total_file_count}개 파일 중 {non_txt_count}개가 .txt가 아닙니다."
            )

        for file_path_str in sampled_paths:
            file_path = Path(file_path_str)
            filename = file_path.name

            if not file_path.exists():
                errors.append(f"[{filename}] 파일이 존재하지 않습니다: {file_path_str}")
                continue

            if not file_path.suffix.lower() == ".txt":
                errors.append(f"[{filename}] YOLO 포맷은 .txt 파일이어야 합니다.")
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as txt_file:
                    lines = txt_file.readlines()
            except Exception as read_error:
                errors.append(f"[{filename}] 파일 읽기 실패: {read_error}")
                continue

            non_empty_lines = [line.strip() for line in lines if line.strip()]
            total_label_count += len(non_empty_lines)

            # 샘플 라인 검사
            sample_lines = non_empty_lines[:max_sample_lines]
            for line_number, line in enumerate(sample_lines, start=1):
                parts = line.split()
                if len(parts) != 5:
                    errors.append(
                        f"[{filename}:{line_number}] 5개 값이어야 합니다 "
                        f"(class_id x y w h), 실제: {len(parts)}개"
                    )
                    continue

                try:
                    class_id = int(parts[0])
                    if class_id < 0:
                        errors.append(f"[{filename}:{line_number}] class_id가 음수입니다: {class_id}")
                        continue
                    class_id_set.add(class_id)
                except ValueError:
                    errors.append(f"[{filename}:{line_number}] class_id가 정수가 아닙니다: {parts[0]}")
                    continue

                for idx, coord_name in enumerate(["x", "y", "w", "h"], start=1):
                    try:
                        value = float(parts[idx])
                        if not (0.0 <= value <= 1.0):
                            errors.append(
                                f"[{filename}:{line_number}] {coord_name}={value} — 0~1 범위를 벗어남"
                            )
                    except ValueError:
                        errors.append(
                            f"[{filename}:{line_number}] {coord_name}이 숫자가 아닙니다: {parts[idx]}"
                        )

        is_valid = len(errors) == 0
        summary = None
        if is_valid:
            sorted_class_ids = sorted(class_id_set)

            # 메타 파일(yaml)이 있으면 class name 매핑 추출
            class_names_from_meta: list[str] | None = None
            if annotation_meta_file:
                meta_path = Path(annotation_meta_file)
                if meta_path.exists():
                    from app.pipeline.io.yolo_io import parse_yolo_yaml
                    class_names_from_meta = parse_yolo_yaml(meta_path)

            # class_mapping 구성:
            # meta 파일이 있으면 전체 클래스 목록을 사용 (데이터 미등장 클래스 포함).
            # 이미지 추가 시 새로운 class가 등장해도 매핑이 이미 존재하도록 보장한다.
            if class_names_from_meta:
                class_mapping = {
                    str(cid): class_names_from_meta[cid]
                    for cid in range(len(class_names_from_meta))
                }
            else:
                class_mapping = {str(cid): str(cid) for cid in sorted_class_ids}

            # class_count: meta 파일이 있으면 전체 정의된 클래스 수, 없으면 데이터 등장 클래스 수
            effective_class_count = (
                len(class_names_from_meta) if class_names_from_meta else len(class_id_set)
            )

            summary = {
                "total_file_count": total_file_count,
                "sampled_file_count": len(sampled_paths) if is_sampled else total_file_count,
                "is_sampled": is_sampled,
                "total_label_count": total_label_count,
                "unique_class_ids": sorted_class_ids,
                "class_count": effective_class_count,
                "class_mapping": class_mapping,
            }

        return FormatValidateResponse(valid=is_valid, errors=errors, summary=summary)

    async def _next_version(self, split_id: str) -> str:
        """
        해당 split_id(DatasetSplit)의 다음 버전 자동 계산 (v7.9 3계층 분리 반영).

        버전 정책: {major}.{minor}
        - major: 사용자가 명시적으로 파이프라인을 실행할 때 증가
        - minor: 향후 automation이 파이프라인을 자동 실행할 때 증가 (미구현)
        RAW 데이터셋 수동 등록 시에는 항상 major를 올린다.
        """
        result = await self.db.execute(
            select(DatasetVersion.version)
            .where(DatasetVersion.split_id == split_id)
            .order_by(DatasetVersion.created_at.desc())
            .limit(1)
        )
        last_version = result.scalar_one_or_none()
        if not last_version:
            return "1.0"

        try:
            parts = last_version.lstrip("v").split(".")
            major = int(parts[0]) + 1
            return f"{major}.0"
        except (IndexError, ValueError):
            return "1.0"

    # -------------------------------------------------------------------------
    # Dataset 개별 조회 / 수정
    # -------------------------------------------------------------------------

    async def get_dataset(self, dataset_id: str) -> DatasetVersion | None:
        """단건 DatasetVersion 조회. 소프트 삭제된 데이터셋은 제외.
        split → group 체인과 pipeline_runs 관계를 함께 로드한다 (v7.9 3계층 분리).
        """
        result = await self.db.execute(
            select(DatasetVersion)
            .where(
                DatasetVersion.id == dataset_id,
                DatasetVersion.deleted_at.is_(None),
            )
            .options(
                # split.group 은 association_proxy 로 노출되지만 selectinload 는 실제
                # relationship 체인 (split → group) 을 따라가야 한다.
                selectinload(DatasetVersion.split_slot).selectinload(DatasetSplit.group),
                selectinload(DatasetVersion.pipeline_runs),
            )
        )
        return result.scalar_one_or_none()

    async def update_dataset(self, dataset: Dataset, data: DatasetUpdate) -> Dataset:
        """
        Dataset 개별 수정 (부분 업데이트).
        annotation_format이 변경되면 기존 검증 결과(class_count, metadata)를 초기화한다.
        """
        update_data = data.model_dump(exclude_unset=True)

        # 포맷 변경 시 클래스 정보 초기화 — 재검증 필요
        new_format = update_data.get("annotation_format")
        if new_format and new_format != dataset.annotation_format:
            dataset.class_count = None
            dataset.metadata_ = None
            logger.info(
                "포맷 변경으로 클래스 정보 초기화",
                dataset_id=dataset.id,
                old_format=dataset.annotation_format,
                new_format=new_format,
            )

        for field, value in update_data.items():
            setattr(dataset, field, value)
        await self.db.flush()
        await self.db.refresh(dataset)
        return dataset

    async def replace_annotation_meta_file(
        self, dataset: Dataset, source_meta_file_path: str
    ) -> Dataset:
        """
        기존 데이터셋의 어노테이션 메타 파일을 교체한다.

        1. 업로드 경로의 파일을 검증
        2. 데이터셋 루트 디렉토리로 복사 (기존 파일 덮어쓰기)
        3. DB의 annotation_meta_file 컬럼 업데이트

        Args:
            dataset: 대상 Dataset 객체
            source_meta_file_path: 교체할 메타 파일 절대경로 (업로드 경로)

        Returns:
            업데이트된 Dataset 객체
        """
        # 소스 파일 경로 검증
        validated_path = self._validate_browse_path(source_meta_file_path, expect_dir=False)

        # 관리 스토리지로 복사 (기존 파일이 있으면 덮어쓰기됨)
        new_filename = self.storage.copy_annotation_meta_file(validated_path, dataset.storage_uri)
        logger.info(
            "어노테이션 메타 파일 교체 완료",
            dataset_id=dataset.id,
            old_file=dataset.annotation_meta_file,
            new_file=new_filename,
        )

        # DB 업데이트
        dataset.annotation_meta_file = new_filename
        await self.db.flush()
        await self.db.refresh(dataset)
        return dataset

    # -------------------------------------------------------------------------
    # 클래스 정보 추출 및 저장
    # -------------------------------------------------------------------------

    def _resolve_annotation_absolute_paths(self, dataset: Dataset) -> list[str]:
        """
        Dataset의 storage_uri + annotation_files로 절대 경로 목록 구성.

        저장 구조: {LOCAL_STORAGE_BASE}/{storage_uri}/{annotations_dirname}/{filename}
        """
        base_path = Path(settings.local_storage_base) / dataset.storage_uri
        annotations_dir = base_path / app_config.annotations_dirname

        if not dataset.annotation_files:
            raise ValueError(f"어노테이션 파일 목록이 비어있습니다: dataset_id={dataset.id}")

        absolute_paths: list[str] = []
        for filename in dataset.annotation_files:
            file_path = annotations_dir / filename
            if not file_path.exists():
                raise ValueError(f"어노테이션 파일이 존재하지 않습니다: {file_path}")
            absolute_paths.append(str(file_path))

        return absolute_paths

    def _resolve_annotation_meta_absolute_path(self, dataset: Dataset) -> str | None:
        """
        Dataset의 annotation_meta_file이 있으면 절대 경로로 변환.
        메타 파일은 데이터셋 루트에 위치한다.
        """
        if not dataset.annotation_meta_file:
            return None
        base_path = Path(settings.local_storage_base) / dataset.storage_uri
        meta_path = base_path / dataset.annotation_meta_file
        if not meta_path.exists():
            logger.warning(
                "어노테이션 메타 파일이 존재하지 않음",
                path=str(meta_path), dataset_id=dataset.id,
            )
            return None
        return str(meta_path)

    async def _extract_and_persist_class_info(self, dataset: Dataset) -> None:
        """
        이미 저장된 데이터셋의 어노테이션 파일에서 클래스 정보를 추출하여 DB에 저장.
        register_dataset 직후 자동 호출용 (best-effort).
        """
        annotation_format = (dataset.annotation_format or "").upper()
        if annotation_format not in ("COCO", "YOLO"):
            return

        absolute_paths = self._resolve_annotation_absolute_paths(dataset)
        meta_abs_path = self._resolve_annotation_meta_absolute_path(dataset)
        validation_request = FormatValidateRequest(
            annotation_format=annotation_format,
            annotation_files=absolute_paths,
            annotation_meta_file=meta_abs_path,
        )
        result = self.validate_annotation_format(validation_request)

        if result.valid and result.summary:
            self._apply_class_info_to_dataset(dataset, result.summary, annotation_format)
            await self.db.flush()

    async def validate_and_persist_class_info(
        self, dataset_id: str, annotation_format: str
    ) -> FormatValidateResponse:
        """
        이미 등록된 데이터셋의 어노테이션을 검증하고 클래스 정보를 DB에 저장.

        상세 페이지에서 '검증' 버튼 클릭 시 호출.
        1. dataset의 storage_uri + annotation_files로 절대 경로 구성
        2. validate_annotation_format 호출
        3. 결과에서 class_count, class_mapping 추출하여 DB 업데이트
        """
        dataset = await self.get_dataset(dataset_id)
        if not dataset:
            raise ValueError(f"Dataset을 찾을 수 없습니다: {dataset_id}")

        absolute_paths = self._resolve_annotation_absolute_paths(dataset)
        meta_abs_path = self._resolve_annotation_meta_absolute_path(dataset)
        validation_request = FormatValidateRequest(
            annotation_format=annotation_format.upper(),
            annotation_files=absolute_paths,
            annotation_meta_file=meta_abs_path,
        )
        result = self.validate_annotation_format(validation_request)

        if result.valid and result.summary:
            # 포맷 변경이 있으면 함께 업데이트
            dataset.annotation_format = annotation_format.upper()
            self._apply_class_info_to_dataset(
                dataset, result.summary, annotation_format.upper()
            )
            await self.db.flush()
            await self.db.refresh(dataset)
            logger.info(
                "클래스 정보 저장 완료",
                dataset_id=dataset_id,
                class_count=dataset.class_count,
            )

        return result

    @staticmethod
    def _apply_class_info_to_dataset(
        dataset: Dataset, summary: dict, annotation_format: str
    ) -> None:
        """검증 결과 summary에서 클래스 정보를 추출하여 Dataset 객체에 적용."""
        class_mapping = summary.get("class_mapping", {})

        if annotation_format == "COCO":
            class_count = summary.get("total_category_count", len(class_mapping))
        else:
            class_count = summary.get("class_count", len(class_mapping))

        dataset.class_count = class_count
        dataset.metadata_ = {
            "class_info": {
                "class_count": class_count,
                "class_mapping": class_mapping,
            },
        }

    # -------------------------------------------------------------------------
    # 데이터셋 뷰어: 샘플 인덱스 캐싱 + 샘플 목록 + EDA 통계
    # -------------------------------------------------------------------------

    SAMPLE_INDEX_FILENAME = "sample_index.json"
    # 통일포맷 전환 후 캐시 구조 변경 (v1: category_id 기반 → v2: category_name 기반)
    SAMPLE_INDEX_SCHEMA_VERSION = 2

    # Classification (CLS_MANIFEST) 전용 캐시 — 구조가 달라 별도 파일로 분리.
    CLASSIFICATION_SAMPLE_INDEX_FILENAME = "classification_sample_index.json"
    CLASSIFICATION_SAMPLE_INDEX_SCHEMA_VERSION = 1

    def _load_dataset_meta(self, dataset: Dataset) -> "DatasetMeta | None":
        """
        데이터셋의 annotation 파일을 파싱하여 DatasetMeta로 반환.
        READY 상태이고 annotation_files가 있을 때만 동작.
        파싱 실패 시 None 반환.
        """
        annotation_format = dataset.annotation_format or dataset.group.annotation_format
        if not annotation_format or annotation_format == "NONE":
            return None
        if not dataset.annotation_files:
            return None

        try:
            from lib.pipeline.dag_executor import load_source_meta_from_storage
            return load_source_meta_from_storage(
                storage=self.storage,
                storage_uri=dataset.storage_uri,
                annotation_format=annotation_format,
                annotation_files=dataset.annotation_files,
                annotation_meta_file=dataset.annotation_meta_file,
                dataset_id=dataset.id,
                skip_image_sizes=True,
            )
        except Exception as parse_error:
            logger.warning(
                "annotation 파싱 실패",
                dataset_id=dataset.id,
                error=str(parse_error),
            )
            return None

    def _get_sample_index_path(self, dataset: Dataset) -> Path:
        """sample_index.json의 절대경로를 반환."""
        return self.storage.resolve_path(dataset.storage_uri) / self.SAMPLE_INDEX_FILENAME

    def _get_or_create_sample_index(self, dataset: Dataset) -> dict | None:
        """
        sample_index.json 캐시를 반환한다.
        파일이 있으면 읽어서 반환, 없으면 annotation을 파싱하여 생성 후 반환.

        캐시 구조 (schema_version=2, 통일포맷):
            {
                "schema_version": 2,
                "categories": ["person", "car", ...],
                "images": [
                    {
                        "image_id": 1,
                        "file_name": "000001.jpg",
                        "width": 640,
                        "height": 480,
                        "annotation_count": 3,
                        "annotations": [
                            {"category_name": "person", "bbox": [...], "area": 1234.5},
                            ...
                        ]
                    },
                    ...
                ],
                "bbox_normalized": false
            }

        READY 데이터셋은 내용이 변하지 않으므로 캐시 무효화가 불필요하다.
        """
        index_path = self._get_sample_index_path(dataset)

        # 캐시 파일이 이미 있으면 읽기만 하고 반환 (스키마 버전 일치 시)
        if index_path.exists():
            try:
                cached = json.loads(index_path.read_text(encoding="utf-8"))
                if cached.get("schema_version") == self.SAMPLE_INDEX_SCHEMA_VERSION:
                    return cached
                logger.info(
                    "sample_index.json 스키마 버전 불일치 — 재생성",
                    dataset_id=dataset.id,
                    cached_version=cached.get("schema_version"),
                    expected_version=self.SAMPLE_INDEX_SCHEMA_VERSION,
                )
            except Exception as read_error:
                logger.warning(
                    "sample_index.json 읽기 실패 — 재생성",
                    dataset_id=dataset.id,
                    error=str(read_error),
                )

        # 캐시 없음 → annotation 전체 파싱 후 인덱스 생성
        meta = self._load_dataset_meta(dataset)
        if meta is None:
            return None

        images = []
        for record in meta.image_records:
            annotation_items = []
            for ann in record.annotations:
                area = None
                if ann.bbox and len(ann.bbox) == 4:
                    area = round(ann.bbox[2] * ann.bbox[3], 1)
                annotation_items.append({
                    "category_name": ann.category_name,
                    "bbox": ann.bbox,
                    "area": area,
                })

            images.append({
                "image_id": record.image_id,
                "file_name": record.file_name,
                "width": record.width,
                "height": record.height,
                "annotation_count": len(record.annotations),
                "annotations": annotation_items,
            })

        # 이미지 크기 정보가 없으면 bbox가 정규화 좌표(0~1)로 저장됨 (YOLO + skip_image_sizes)
        has_image_sizes = any(record.width is not None for record in meta.image_records)

        sample_index = {
            "schema_version": self.SAMPLE_INDEX_SCHEMA_VERSION,
            "categories": meta.categories,
            "images": images,
            "bbox_normalized": not has_image_sizes,
        }

        # 디스크에 캐시 저장
        try:
            index_path.write_text(
                json.dumps(sample_index, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(
                "sample_index.json 생성 완료",
                dataset_id=dataset.id,
                image_count=len(images),
            )
        except Exception as write_error:
            logger.warning(
                "sample_index.json 저장 실패 — 캐시 없이 계속 진행",
                dataset_id=dataset.id,
                error=str(write_error),
            )

        return sample_index

    def get_sample_list(
        self,
        dataset: Dataset,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """
        데이터셋의 이미지 + annotation 목록을 페이지네이션하여 반환.
        sample_index.json 캐시가 있으면 파싱 없이 바로 응답한다.
        nginx static 서빙 URL을 포함한다.
        """
        sample_index = self._get_or_create_sample_index(dataset)
        if sample_index is None:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "categories": [],
            }

        all_images = sample_index["images"]
        total = len(all_images)

        # 이미지 서빙 URL base
        image_url_base = self.storage.get_image_serve_url(
            f"{dataset.storage_uri}/images"
        )

        start_index = (page - 1) * page_size
        end_index = min(start_index + page_size, total)
        page_images = all_images[start_index:end_index]

        # 각 이미지에 서빙 URL 부여
        items = []
        for image_entry in page_images:
            items.append({
                **image_entry,
                "image_url": f"{image_url_base}/{image_entry['file_name']}",
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "categories": sample_index["categories"],
            "bbox_normalized": sample_index.get("bbox_normalized", False),
        }

    def get_eda_stats(self, dataset: Dataset) -> dict:
        """
        데이터셋의 annotation을 분석하여 EDA 통계를 반환.
        sample_index.json 캐시가 있으면 파싱 없이 바로 계산한다.
        클래스 분포, bbox 크기 분포, 이미지 해상도 범위 등.
        """
        sample_index = self._get_or_create_sample_index(dataset)
        if sample_index is None:
            return {
                "total_images": dataset.image_count or 0,
                "total_annotations": 0,
                "total_classes": dataset.class_count or 0,
                "images_without_annotations": 0,
                "class_distribution": [],
                "bbox_area_distribution": [],
            }

        all_images = sample_index["images"]
        categories = sample_index["categories"]

        # 클래스별 통계 (통일포맷: category_name 기반)
        class_annotation_count: dict[str, int] = {}
        class_image_set: dict[str, set] = {}
        total_annotations = 0
        images_without_annotations = 0

        # 이미지 해상도 범위
        widths = []
        heights = []

        # bbox area 수집
        bbox_areas: list[float] = []

        for image_entry in all_images:
            if image_entry.get("width") is not None:
                widths.append(image_entry["width"])
            if image_entry.get("height") is not None:
                heights.append(image_entry["height"])

            annotations = image_entry.get("annotations", [])
            if not annotations:
                images_without_annotations += 1

            seen_categories_in_image: set[str] = set()
            for ann in annotations:
                total_annotations += 1
                category_name = ann["category_name"]
                class_annotation_count[category_name] = (
                    class_annotation_count.get(category_name, 0) + 1
                )
                seen_categories_in_image.add(category_name)

                if ann.get("bbox") and len(ann["bbox"]) == 4:
                    bbox_areas.append(ann["bbox"][2] * ann["bbox"][3])

            for category_name in seen_categories_in_image:
                if category_name not in class_image_set:
                    class_image_set[category_name] = set()
                class_image_set[category_name].add(image_entry["image_id"])

        # 클래스 분포 (annotation 수 내림차순)
        class_distribution = []
        for category_name, annotation_count in sorted(
            class_annotation_count.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            class_distribution.append({
                "category_name": category_name,
                "annotation_count": annotation_count,
                "image_count": len(class_image_set.get(category_name, set())),
            })

        # bbox 면적 분포 (구간별)
        bbox_area_distribution = _compute_bbox_area_distribution(bbox_areas)

        return {
            "total_images": len(all_images),
            "total_annotations": total_annotations,
            "total_classes": len(categories),
            "images_without_annotations": images_without_annotations,
            "class_distribution": class_distribution,
            "bbox_area_distribution": bbox_area_distribution,
            "image_width_min": min(widths) if widths else None,
            "image_width_max": max(widths) if widths else None,
            "image_height_min": min(heights) if heights else None,
            "image_height_max": max(heights) if heights else None,
        }


    # =========================================================================
    # Classification (CLS_MANIFEST) 전용 뷰어/EDA
    # =========================================================================
    # manifest.jsonl + head_schema.json을 읽어 간단한 디스크 캐시를 만든다.
    # sample_index.json과 파일을 분리해 둔 이유는 스키마가 근본적으로 달라(bbox→head별 label)
    # 버전 관리를 독립적으로 하고 detection 캐시가 오염되지 않도록 하기 위함.

    def _get_classification_sample_index_path(self, dataset: Dataset) -> Path:
        """classification_sample_index.json의 절대경로."""
        return (
            self.storage.resolve_path(dataset.storage_uri)
            / self.CLASSIFICATION_SAMPLE_INDEX_FILENAME
        )

    def _get_or_create_classification_sample_index(
        self, dataset: Dataset,
    ) -> dict | None:
        """
        Classification 데이터셋의 manifest.jsonl / head_schema.json을 읽어 인덱스 생성.

        캐시 구조 (schema_version=1):
            {
              "schema_version": 1,
              "heads": [{"name":..., "multi_label":..., "classes":[...]}],
              "images": [
                {
                  "sha": "...",
                  "stored_filename": "{sha}.{ext}",
                  "original_filename": "img_0001.jpg",
                  "labels": {"head1": ["class_a"], "head2": []},
                  "width": 640,
                  "height": 480
                },
                ...
              ]
            }

        이미지 width/height는 PIL로 한 번 읽어 캐시에 남긴다 (EDA 해상도 분포용).
        """
        index_path = self._get_classification_sample_index_path(dataset)

        # 기존 캐시 사용
        if index_path.exists():
            try:
                cached = json.loads(index_path.read_text(encoding="utf-8"))
                if (
                    cached.get("schema_version")
                    == self.CLASSIFICATION_SAMPLE_INDEX_SCHEMA_VERSION
                ):
                    return cached
                logger.info(
                    "classification_sample_index.json 스키마 버전 불일치 — 재생성",
                    dataset_id=dataset.id,
                    cached_version=cached.get("schema_version"),
                    expected_version=self.CLASSIFICATION_SAMPLE_INDEX_SCHEMA_VERSION,
                )
            except Exception as read_error:
                logger.warning(
                    "classification_sample_index.json 읽기 실패 — 재생성",
                    dataset_id=dataset.id,
                    error=str(read_error),
                )

        # 캐시 없음 → manifest + head_schema 파싱
        dataset_root = self.storage.resolve_path(dataset.storage_uri)

        # head_schema.json: 보통 dataset.annotation_meta_file 에 저장돼 있지만
        # 안전하게 고정 경로도 fallback으로 확인한다.
        head_schema_path: Path | None = None
        if dataset.annotation_meta_file:
            candidate = dataset_root / dataset.annotation_meta_file
            if candidate.exists():
                head_schema_path = candidate
        if head_schema_path is None:
            fallback = dataset_root / "head_schema.json"
            if fallback.exists():
                head_schema_path = fallback
        if head_schema_path is None:
            logger.warning(
                "head_schema.json을 찾을 수 없음",
                dataset_id=dataset.id,
                storage_uri=dataset.storage_uri,
            )
            return None

        # manifest.jsonl
        manifest_path: Path | None = None
        if dataset.annotation_files:
            candidate = dataset_root / dataset.annotation_files[0]
            if candidate.exists():
                manifest_path = candidate
        if manifest_path is None:
            fallback = dataset_root / "manifest.jsonl"
            if fallback.exists():
                manifest_path = fallback
        if manifest_path is None:
            logger.warning(
                "manifest.jsonl을 찾을 수 없음",
                dataset_id=dataset.id,
                storage_uri=dataset.storage_uri,
            )
            return None

        try:
            head_schema = json.loads(head_schema_path.read_text(encoding="utf-8"))
        except Exception as schema_error:
            logger.warning(
                "head_schema.json 파싱 실패",
                dataset_id=dataset.id,
                error=str(schema_error),
            )
            return None

        images_dir_abs = dataset_root / "images"

        # 이미지 크기는 PIL로 한 번 읽어 캐시에 반영.
        # 이미지가 수십만 장이면 시간이 걸릴 수 있으므로 실패/누락을 허용한다.
        try:
            from PIL import Image as pil_image
        except ImportError:
            pil_image = None  # type: ignore[assignment]
            logger.warning("Pillow가 없어 이미지 크기 정보를 수집하지 못합니다.")

        images: list[dict] = []
        try:
            with manifest_path.open("r", encoding="utf-8") as manifest_file:
                for raw_line in manifest_file:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sha = entry.get("sha") or ""
                    stored_rel = entry.get("filename") or ""
                    # "images/{sha}.ext" 형태 — 파일명만 추출해 저장해 두면 이후 URL 구성에 편리.
                    stored_filename = Path(stored_rel).name if stored_rel else ""

                    width = height = None
                    if pil_image is not None and stored_filename:
                        image_abs = images_dir_abs / stored_filename
                        if image_abs.exists():
                            try:
                                with pil_image.open(image_abs) as img:
                                    width, height = img.width, img.height
                            except Exception:
                                pass

                    images.append({
                        "sha": sha,
                        "stored_filename": stored_filename,
                        "original_filename": entry.get("original_filename") or stored_filename,
                        "labels": entry.get("labels") or {},
                        "width": width,
                        "height": height,
                    })
        except Exception as manifest_error:
            logger.warning(
                "manifest.jsonl 파싱 실패",
                dataset_id=dataset.id,
                error=str(manifest_error),
            )
            return None

        classification_index = {
            "schema_version": self.CLASSIFICATION_SAMPLE_INDEX_SCHEMA_VERSION,
            "heads": head_schema.get("heads") or [],
            "images": images,
        }

        try:
            index_path.write_text(
                json.dumps(classification_index, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(
                "classification_sample_index.json 생성 완료",
                dataset_id=dataset.id,
                image_count=len(images),
            )
        except Exception as write_error:
            logger.warning(
                "classification_sample_index.json 저장 실패 — 캐시 없이 계속 진행",
                dataset_id=dataset.id,
                error=str(write_error),
            )

        return classification_index

    def get_classification_sample_list(
        self,
        dataset: Dataset,
        page: int = 1,
        page_size: int = 50,
        head_filters: dict[str, list[str]] | None = None,
    ) -> dict:
        """Classification 샘플 뷰어용 이미지 목록 반환.

        head_filters: {head_name: [class_name, ...]} — 같은 head 내 class는 OR,
        서로 다른 head 간에는 AND로 결합한다. 페이지네이션 이전에 적용되므로
        프론트엔드가 페이지를 넘기며 필터가 깨지는 문제를 피할 수 있다.
        """
        classification_index = self._get_or_create_classification_sample_index(dataset)
        if classification_index is None:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "heads": [],
            }

        all_images = classification_index["images"]

        # head_filters 적용 — 빈 dict/None이면 통과
        if head_filters:
            filtered_images = []
            for entry in all_images:
                labels = entry.get("labels") or {}
                # 모든 head 조건이 충족되어야 한다(AND)
                if all(
                    any(cls in (labels.get(head_name) or []) for cls in class_names)
                    for head_name, class_names in head_filters.items()
                ):
                    filtered_images.append(entry)
            all_images = filtered_images

        total = len(all_images)

        # 이미지 서빙 URL base. detection과 동일하게 {storage_uri}/images/ 아래 서빙.
        image_url_base = self.storage.get_image_serve_url(
            f"{dataset.storage_uri}/images"
        )

        start_index = (page - 1) * page_size
        end_index = min(start_index + page_size, total)
        page_images = all_images[start_index:end_index]

        items = []
        for entry in page_images:
            stored_filename = entry.get("stored_filename") or ""
            original_filename = entry.get("original_filename") or ""
            # merge rename 등으로 현재 파일명과 원본이 달라진 경우에만 original 노출.
            # 캐시 빌더가 original 결측 시 stored 로 채워 넣으므로 문자열 비교로 판별 가능.
            original_display: str | None = (
                original_filename
                if original_filename and original_filename != stored_filename
                else None
            )
            items.append({
                "file_name": stored_filename,
                "original_file_name": original_display,
                "image_url": f"{image_url_base}/{stored_filename}" if stored_filename else "",
                "width": entry.get("width"),
                "height": entry.get("height"),
                "labels": entry.get("labels") or {},
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "heads": classification_index.get("heads") or [],
        }

    def get_classification_eda_stats(self, dataset: Dataset) -> dict:
        """Classification 데이터셋의 EDA 통계 계산.

        - per_head_distribution: head별 class 분포 + labeled/unlabeled 수
        - head_cooccurrence: 서로 다른 head 쌍별 (class × class) joint count 행렬
        - multi_label_positive_ratio: multi_label head의 class별 positive ratio
        - 이미지 해상도 min/max
        """
        classification_index = self._get_or_create_classification_sample_index(dataset)
        if classification_index is None:
            return {
                "total_images": dataset.image_count or 0,
                "per_head_distribution": [],
                "head_cooccurrence": [],
                "multi_label_positive_ratio": [],
            }

        heads: list[dict] = classification_index.get("heads") or []
        all_images: list[dict] = classification_index.get("images") or []

        # 1) 해상도 min/max
        widths = [img["width"] for img in all_images if img.get("width") is not None]
        heights = [img["height"] for img in all_images if img.get("height") is not None]

        # 2) head별 class 분포 + labeled/unlabeled
        per_head_distribution: list[dict] = []
        for head in heads:
            head_name = head.get("name") or ""
            multi_label = bool(head.get("multi_label"))
            class_list: list[str] = list(head.get("classes") or [])
            class_to_count: dict[str, int] = {class_name: 0 for class_name in class_list}

            labeled = 0
            unlabeled = 0
            for img in all_images:
                labels_for_head = (img.get("labels") or {}).get(head_name) or []
                if not labels_for_head:
                    unlabeled += 1
                    continue
                labeled += 1
                # multi-label이면 이미지가 여러 class를 가질 수 있다 — 각 class에 +1
                for class_name in labels_for_head:
                    if class_name in class_to_count:
                        class_to_count[class_name] += 1

            per_head_distribution.append({
                "head_name": head_name,
                "multi_label": multi_label,
                "labeled_image_count": labeled,
                "unlabeled_image_count": unlabeled,
                "classes": [
                    {"class_name": class_name, "image_count": class_to_count[class_name]}
                    for class_name in class_list
                ],
            })

        # 3) head 쌍별 co-occurrence. head가 1개면 건너뛴다.
        head_cooccurrence: list[dict] = []
        for a_index in range(len(heads)):
            head_a = heads[a_index]
            head_a_name = head_a.get("name") or ""
            classes_a: list[str] = list(head_a.get("classes") or [])
            class_a_index: dict[str, int] = {name: i for i, name in enumerate(classes_a)}

            for b_index in range(a_index + 1, len(heads)):
                head_b = heads[b_index]
                head_b_name = head_b.get("name") or ""
                classes_b: list[str] = list(head_b.get("classes") or [])
                class_b_index: dict[str, int] = {name: i for i, name in enumerate(classes_b)}

                a_counts = [0] * len(classes_a)
                b_counts = [0] * len(classes_b)
                joint_counts = [[0] * len(classes_b) for _ in range(len(classes_a))]

                for img in all_images:
                    labels = img.get("labels") or {}
                    labels_a = [c for c in (labels.get(head_a_name) or []) if c in class_a_index]
                    labels_b = [c for c in (labels.get(head_b_name) or []) if c in class_b_index]
                    if not labels_a and not labels_b:
                        continue
                    for class_name in labels_a:
                        a_counts[class_a_index[class_name]] += 1
                    for class_name in labels_b:
                        b_counts[class_b_index[class_name]] += 1
                    # 교차 카운트는 두 head 모두 라벨이 있을 때만 증가
                    if labels_a and labels_b:
                        for class_a_name in labels_a:
                            for class_b_name in labels_b:
                                joint_counts[class_a_index[class_a_name]][
                                    class_b_index[class_b_name]
                                ] += 1

                head_cooccurrence.append({
                    "head_a": head_a_name,
                    "head_b": head_b_name,
                    "classes_a": classes_a,
                    "classes_b": classes_b,
                    "a_counts": a_counts,
                    "b_counts": b_counts,
                    "joint_counts": joint_counts,
                })

        # 4) multi-label head의 positive ratio
        # 분모는 해당 head에 라벨이 하나라도 있는 이미지 수로 한정 (unlabeled는 제외).
        # 이유: "이 attribute가 라벨링됐을 때" 중 positive 비율이 imbalance 지표로 의미가 있음.
        multi_label_positive_ratio: list[dict] = []
        for dist in per_head_distribution:
            if not dist["multi_label"]:
                continue
            labeled = dist["labeled_image_count"]
            for class_entry in dist["classes"]:
                positive_count = class_entry["image_count"]
                negative_count = max(labeled - positive_count, 0)
                denom = labeled
                positive_ratio = (positive_count / denom) if denom > 0 else 0.0
                multi_label_positive_ratio.append({
                    "head_name": dist["head_name"],
                    "class_name": class_entry["class_name"],
                    "positive_count": positive_count,
                    "negative_count": negative_count,
                    "positive_ratio": round(positive_ratio, 4),
                })

        return {
            "total_images": len(all_images),
            "image_width_min": min(widths) if widths else None,
            "image_width_max": max(widths) if widths else None,
            "image_height_min": min(heights) if heights else None,
            "image_height_max": max(heights) if heights else None,
            "per_head_distribution": per_head_distribution,
            "head_cooccurrence": head_cooccurrence,
            "multi_label_positive_ratio": multi_label_positive_ratio,
        }


def _compute_bbox_area_distribution(
    bbox_areas: list[float],
) -> list[dict[str, str | int]]:
    """bbox 면적을 구간별로 분류하여 분포를 반환한다."""
    if not bbox_areas:
        return []

    # 고정 구간: 면적 기준
    bins = [
        (0, 1024, "Tiny (< 32²)"),
        (1024, 9216, "Small (32²–96²)"),
        (9216, 65536, "Medium (96²–256²)"),
        (65536, 262144, "Large (256²–512²)"),
        (262144, float("inf"), "XLarge (> 512²)"),
    ]
    distribution = []
    for low, high, label in bins:
        count = sum(1 for area in bbox_areas if low <= area < high)
        if count > 0:
            distribution.append({"range_label": label, "count": count})
    return distribution


# =============================================================================
# Classification head_schema 일관성 헬퍼
# =============================================================================
# 단일 원칙 (설계서 §2-8):
#   "같은 Group 의 모든 Dataset 은 동일 head_schema 를 가진다."
#   head_schema 가 달라지면 type 무관 예외 없이 새 Group 으로 분기해야 한다.
#
# 이에 따라 _diff_head_schema 는 어떤 차이든 발견되면 ValueError 로 차단한다.
# 이전 버전에 있던 NEW_HEAD / NEW_CLASS warning 허용 경로는 제거되었다
# (학습 index 계약의 암묵 변이를 방지 — 과거 학습 결과 해석이 조용히 바뀌던
# 회색지대를 없앰).

def _diff_head_schema(
    existing: dict,
    incoming: dict,
) -> list["ClassificationHeadWarning"]:
    """기존 group head_schema 대비 incoming 을 비교. 어떤 차이든 ValueError.

    반환 타입은 기존 시그니처 호환을 위해 list 로 유지되지만, 이제 차이가
    있으면 반드시 예외로 차단되므로 정상 흐름에서는 빈 리스트만 반환된다.
    """
    # 차이 유형을 먼저 전부 수집한 뒤, 하나라도 있으면 묶어서 ValueError 로 raise.
    existing_heads = {h["name"]: h for h in (existing.get("heads") or [])}
    incoming_heads = {h["name"]: h for h in (incoming.get("heads") or [])}

    diff_messages: list[str] = []

    # (1) incoming 기준: 신규 head / multi_label 변경 / class 변경 검사
    for head_name, incoming_head in incoming_heads.items():
        existing_head = existing_heads.get(head_name)
        if existing_head is None:
            diff_messages.append(
                f"head '{head_name}' 이(가) 기존 그룹에 없습니다 (NEW_HEAD)"
            )
            continue

        if bool(existing_head.get("multi_label")) != bool(incoming_head.get("multi_label")):
            diff_messages.append(
                f"head '{head_name}' 의 multi_label 값이 기존과 다릅니다 "
                f"(기존={bool(existing_head.get('multi_label'))}, "
                f"요청={bool(incoming_head.get('multi_label'))})"
            )

        existing_classes: list[str] = list(existing_head.get("classes") or [])
        incoming_classes: list[str] = list(incoming_head.get("classes") or [])

        if existing_classes != incoming_classes:
            diff_messages.append(
                f"head '{head_name}' 의 classes 가 기존과 다릅니다 "
                f"(기존={existing_classes}, 요청={incoming_classes})"
            )

    # (2) existing 기준: incoming 에서 빠진 head 검사 (head 삭제)
    for head_name in existing_heads:
        if head_name not in incoming_heads:
            diff_messages.append(
                f"기존 그룹의 head '{head_name}' 이(가) 요청 schema 에서 빠졌습니다"
            )

    if diff_messages:
        raise ValueError(
            "기존 그룹의 head_schema 와 달라졌습니다. 설계서 §2-8 에 따라 "
            "schema 가 다른 데이터는 새 그룹으로 등록해야 합니다. 차이: "
            + "; ".join(diff_messages)
        )

    return []
