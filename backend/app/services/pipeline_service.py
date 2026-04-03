"""
파이프라인 실행 서비스.

파이프라인 제출(submit) → Celery 태스크 디스패치, 실행 상태 조회 등을 처리한다.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage_client
from app.models.all_models import (
    Dataset,
    DatasetGroup,
    PipelineExecution,
)
from app.schemas.pipeline import PipelineSubmitResponse
from lib.pipeline.config import PipelineConfig

logger = structlog.get_logger(__name__)


class PipelineService:
    """파이프라인 실행 관련 비즈니스 로직."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = get_storage_client()

    # -------------------------------------------------------------------------
    # 파이프라인 제출
    # -------------------------------------------------------------------------

    async def submit_pipeline(self, config: PipelineConfig) -> PipelineSubmitResponse:
        """
        파이프라인 실행을 제출한다.

        1. DatasetGroup 조회 또는 생성 (config.name + config.output.dataset_type)
        2. Dataset 생성 (status=PENDING)
        3. PipelineExecution 생성 (status=PENDING)
        4. Celery 태스크 디스패치
        5. PipelineSubmitResponse 반환

        Args:
            config: DAG 기반 파이프라인 설정 (Pydantic 모델)

        Returns:
            PipelineSubmitResponse (execution_id, celery_task_id, message)
        """
        dataset_type = config.output.dataset_type.upper()
        annotation_format = config.output.annotation_format or "NONE"
        split = config.output.split.upper()

        # ── DatasetGroup 조회 또는 생성 ──
        group = await self._find_or_create_dataset_group(
            name=config.name,
            dataset_type=dataset_type,
            annotation_format=annotation_format,
        )

        # ── 버전 자동 생성 ──
        version = await self._next_version(group.id, split)
        logger.info(
            "파이프라인 출력 버전 결정",
            group_name=group.name, split=split, version=version,
        )

        # ── storage_uri 사전 생성 ──
        storage_uri = self.storage.build_dataset_uri(
            dataset_type=dataset_type,
            name=config.name,
            split=split,
            version=version,
        )

        # ── Dataset 생성 (status=PENDING) ──
        dataset = Dataset(
            id=str(uuid.uuid4()),
            group_id=group.id,
            split=split,
            version=version,
            annotation_format=annotation_format,
            storage_uri=storage_uri,
            status="PENDING",
        )
        self.db.add(dataset)
        await self.db.flush()
        logger.info("출력 Dataset 생성", dataset_id=dataset.id, storage_uri=storage_uri)

        # ── PipelineExecution 생성 ──
        execution = PipelineExecution(
            id=str(uuid.uuid4()),
            output_dataset_id=dataset.id,
            config=config.model_dump(),
            status="PENDING",
        )
        self.db.add(execution)
        await self.db.flush()

        # ── Celery 태스크 디스패치 ──
        from app.tasks.pipeline_tasks import run_pipeline

        celery_result = run_pipeline.delay(
            execution.id,
            config.model_dump(),
        )
        celery_task_id = celery_result.id

        execution.celery_task_id = celery_task_id
        await self.db.flush()

        logger.info(
            "파이프라인 Celery 태스크 디스패치 완료",
            execution_id=execution.id,
            celery_task_id=celery_task_id,
        )

        return PipelineSubmitResponse(
            execution_id=execution.id,
            celery_task_id=celery_task_id,
            message="파이프라인이 제출되었습니다.",
        )

    # -------------------------------------------------------------------------
    # 실행 상태 조회
    # -------------------------------------------------------------------------

    async def get_execution_status(self, execution_id: str) -> PipelineExecution | None:
        """PipelineExecution 단건 조회."""
        result = await self.db.execute(
            select(PipelineExecution).where(PipelineExecution.id == execution_id)
        )
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # 실행 이력 목록
    # -------------------------------------------------------------------------

    async def list_executions(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PipelineExecution], int]:
        """PipelineExecution 목록 조회 (페이지네이션, 최신순)."""
        base_query = select(PipelineExecution)

        count_query = select(func.count()).select_from(base_query.subquery())
        total = await self.db.scalar(count_query) or 0

        list_query = (
            base_query
            .order_by(PipelineExecution.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(list_query)
        items = list(result.scalars().all())

        return items, total

    # -------------------------------------------------------------------------
    # 내부 헬퍼
    # -------------------------------------------------------------------------

    async def _find_or_create_dataset_group(
        self,
        name: str,
        dataset_type: str,
        annotation_format: str,
    ) -> DatasetGroup:
        """
        이름 + dataset_type으로 기존 그룹을 찾고, 없으면 새로 생성한다.
        소프트 삭제된 그룹은 무시한다.
        """
        result = await self.db.execute(
            select(DatasetGroup).where(
                DatasetGroup.name == name,
                DatasetGroup.dataset_type == dataset_type,
                DatasetGroup.deleted_at.is_(None),
            )
        )
        existing_group = result.scalar_one_or_none()

        if existing_group is not None:
            logger.info(
                "기존 DatasetGroup 사용",
                group_id=existing_group.id, group_name=existing_group.name,
            )
            return existing_group

        new_group = DatasetGroup(
            id=str(uuid.uuid4()),
            name=name,
            dataset_type=dataset_type,
            annotation_format=annotation_format,
        )
        self.db.add(new_group)
        await self.db.flush()
        logger.info(
            "신규 DatasetGroup 생성",
            group_id=new_group.id, group_name=new_group.name,
        )
        return new_group

    async def _next_version(self, group_id: str, split: str) -> str:
        """해당 group+split의 다음 버전을 자동 계산한다."""
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
