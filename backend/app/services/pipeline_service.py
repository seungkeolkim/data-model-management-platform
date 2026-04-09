"""
파이프라인 실행 서비스.

파이프라인 제출(submit) → Celery 태스크 디스패치, 실행 상태 조회 등을 처리한다.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.storage import get_storage_client
from app.models.all_models import (
    Dataset,
    DatasetGroup,
    PipelineExecution,
)
from app.schemas.pipeline import PipelineSubmitResponse
from lib.pipeline.config import PipelineConfig
from lib.pipeline.pipeline_validator import (
    PipelineValidationResult,
    validate_pipeline_config_static,
)

logger = structlog.get_logger(__name__)


class PipelineService:
    """파이프라인 실행 관련 비즈니스 로직."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = get_storage_client()

    # -------------------------------------------------------------------------
    # 파이프라인 검증
    # -------------------------------------------------------------------------

    async def validate_pipeline(self, config: PipelineConfig) -> PipelineValidationResult:
        """
        파이프라인 설정을 실행 전에 종합 검증한다.

        정적 검증(lib/ 레이어)과 DB 의존 검증을 모두 수행하여
        하나의 PipelineValidationResult로 통합 반환한다.
        Web UI에서 실행 전 검증 단계에서 호출한다.

        Args:
            config: 검증할 파이프라인 설정

        Returns:
            PipelineValidationResult — is_valid와 개별 issues 목록
        """
        # 1단계: 정적 검증 (DB 불필요)
        result = validate_pipeline_config_static(config)

        # 2단계: DB 의존 검증
        database_result = await self._validate_with_database(config)
        result.merge(database_result)

        if result.is_valid:
            logger.info("파이프라인 검증 통과", name=config.name)
        else:
            logger.warning(
                "파이프라인 검증 실패",
                name=config.name,
                error_count=result.error_count,
                warning_count=result.warning_count,
            )

        return result

    async def _validate_with_database(
        self, config: PipelineConfig
    ) -> PipelineValidationResult:
        """
        DB 조회가 필요한 검증을 수행한다.

        검증 항목:
          1. source dataset_id가 DB에 존재하는지
          2. source dataset의 상태가 READY인지
          3. source dataset에 annotation 파일이 등록되어 있는지
        """
        result = PipelineValidationResult()

        # 모든 source dataset_id 수집 (태스크별로 추적하여 field 정보 제공)
        for task_name, task_config in config.tasks.items():
            for source_dataset_id in task_config.get_source_dataset_ids():
                await self._validate_source_dataset(
                    source_dataset_id, task_name, result,
                )

        return result

    async def _validate_source_dataset(
        self,
        dataset_id: str,
        task_name: str,
        result: PipelineValidationResult,
    ) -> None:
        """
        단일 source dataset_id에 대한 DB 검증을 수행한다.

        검증 항목:
          - DB에 존재하는지
          - 소프트 삭제되지 않았는지
          - 상태가 READY인지
          - annotation_files가 비어있지 않은지
        """
        # Dataset 조회 (group JOIN으로 삭제 여부도 확인)
        query_result = await self.db.execute(
            select(Dataset, DatasetGroup)
            .join(DatasetGroup, Dataset.group_id == DatasetGroup.id)
            .where(Dataset.id == dataset_id)
        )
        row = query_result.first()

        if row is None:
            result.add_error(
                code="SOURCE_DATASET_NOT_FOUND",
                message=(
                    f"태스크 '{task_name}'의 소스 데이터셋 '{dataset_id}'이(가) "
                    f"DB에 존재하지 않습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )
            return

        dataset, dataset_group = row.tuple()

        # 소프트 삭제 확인
        if dataset_group.deleted_at is not None:
            result.add_error(
                code="SOURCE_DATASET_GROUP_DELETED",
                message=(
                    f"태스크 '{task_name}'의 소스 데이터셋 '{dataset_id}'이(가) 속한 "
                    f"그룹 '{dataset_group.name}'이(가) 삭제되었습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )
            return

        # 상태 확인 (READY만 허용)
        if dataset.status != "READY":
            result.add_error(
                code="SOURCE_DATASET_NOT_READY",
                message=(
                    f"태스크 '{task_name}'의 소스 데이터셋 '{dataset_id}'의 "
                    f"상태가 '{dataset.status}'입니다. "
                    f"READY 상태의 데이터셋만 파이프라인 입력으로 사용할 수 있습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )

        # annotation_files 존재 확인
        if not dataset.annotation_files:
            result.add_warning(
                code="SOURCE_DATASET_NO_ANNOTATIONS",
                message=(
                    f"태스크 '{task_name}'의 소스 데이터셋 '{dataset_id}'에 "
                    f"annotation 파일이 등록되어 있지 않습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )

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
        annotation_format = config.output.annotation_format.upper()
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
        """PipelineExecution 단건 조회 (output_dataset eager load)."""
        result = await self.db.execute(
            select(PipelineExecution)
            .options(selectinload(PipelineExecution.output_dataset))
            .where(PipelineExecution.id == execution_id)
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
        """PipelineExecution 목록 조회 (페이지네이션, 최신순, output_dataset eager load)."""
        base_query = select(PipelineExecution)

        count_query = select(func.count()).select_from(base_query.subquery())
        total = await self.db.scalar(count_query) or 0

        list_query = (
            base_query
            .options(selectinload(PipelineExecution.output_dataset))
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
