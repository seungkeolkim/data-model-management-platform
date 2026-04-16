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
from lib.pipeline.config import PartialPipelineConfig, PipelineConfig
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

        # Passthrough 모드(tasks 비어있음)에서도 소스 검증
        if config.is_passthrough and config.passthrough_source_dataset_id:
            await self._validate_source_dataset(
                config.passthrough_source_dataset_id,
                "__passthrough__",
                result,
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

        # ── 소스 데이터셋 그룹들의 task_types 교집합 계산 ──
        source_task_types = await self._intersect_source_task_types(config)

        # ── DatasetGroup 조회 또는 생성 ──
        group = await self._find_or_create_dataset_group(
            name=config.name,
            dataset_type=dataset_type,
            annotation_format=annotation_format,
            task_types=source_task_types,
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
    # Schema 프리뷰
    # -------------------------------------------------------------------------

    async def preview_head_schema(
        self,
        config: PartialPipelineConfig,
        target_ref: str,
    ) -> dict:
        """
        지정 노드 시점의 head_schema 를 계산해 dict 로 반환.

        target_ref 규약:
            - "task_{nodeId}"  : operator/merge 노드 출력
            - "source:{dataset_id}" : dataLoad 노드 출력 (소스 head_schema 그대로)

        반환 dict 구조:
            {
              "task_kind": "classification" | "detection" | "unknown",
              "head_schema": {"heads": [...]} | None,
              "error_code": str | None,
              "error_message": str | None,
            }
        """
        # 지연 import — FastAPI 앱 기동 시 lib 모듈 초기화 순서 문제 회피.
        from lib.pipeline.schema_preview import (
            SchemaPreviewError,
            build_stub_source_meta,
            head_schema_to_list,
            preview_head_schema_at_task,
        )

        # 1) 파이프라인에서 참조하는 모든 source dataset 의 head_schema 를 DB 에서 로드.
        source_dataset_ids = config.get_all_source_dataset_ids()
        source_meta_by_dataset_id: dict[str, object] = {}
        for dataset_id in source_dataset_ids:
            dataset_row = await self.db.execute(
                select(Dataset)
                .options(selectinload(Dataset.group))
                .where(Dataset.id == dataset_id, Dataset.deleted_at.is_(None))
            )
            dataset_obj = dataset_row.scalar_one_or_none()
            if dataset_obj is None:
                return {
                    "task_kind": "unknown",
                    "head_schema": None,
                    "error_code": "SOURCE_NOT_FOUND",
                    "error_message": (
                        f"source dataset_id='{dataset_id}' 를 DB 에서 찾을 수 없습니다."
                    ),
                }
            # head_schema 는 DatasetGroup 에 위치 (SSOT). Dataset 은 group 에서 상속.
            group_head_schema = (
                dataset_obj.group.head_schema if dataset_obj.group else None
            )
            source_meta_by_dataset_id[dataset_id] = build_stub_source_meta(
                dataset_id=dataset_id,
                head_schema_json=group_head_schema,
            )

        # 2) 모든 소스가 detection (head_schema 없음) 이면 프리뷰 대상이 아님.
        any_classification = any(
            getattr(meta, "head_schema", None) is not None
            for meta in source_meta_by_dataset_id.values()
        )
        if not any_classification:
            return {
                "task_kind": "detection",
                "head_schema": None,
                "error_code": None,
                "error_message": None,
            }

        # 3) target_ref 분기.
        if target_ref.startswith("source:"):
            source_dataset_id = target_ref.split(":", 1)[1]
            source_meta = source_meta_by_dataset_id.get(source_dataset_id)
            if source_meta is None:
                return {
                    "task_kind": "unknown",
                    "head_schema": None,
                    "error_code": "TARGET_NOT_FOUND",
                    "error_message": (
                        f"target_ref='{target_ref}' 의 source 를 config 에서 찾지 못했습니다."
                    ),
                }
            head_schema = getattr(source_meta, "head_schema", None)
            return {
                "task_kind": "classification" if head_schema is not None else "detection",
                "head_schema": head_schema_to_list(head_schema),
                "error_code": None,
                "error_message": None,
            }

        # task_{...} 형식.
        try:
            result_meta = preview_head_schema_at_task(
                config=config,
                target_task_name=target_ref,
                source_meta_by_dataset_id=source_meta_by_dataset_id,  # type: ignore[arg-type]
            )
        except SchemaPreviewError as preview_error:
            return {
                "task_kind": "classification",
                "head_schema": None,
                "error_code": preview_error.code,
                "error_message": preview_error.message,
            }

        return {
            "task_kind": "classification" if result_meta.head_schema is not None else "detection",
            "head_schema": head_schema_to_list(result_meta.head_schema),
            "error_code": None,
            "error_message": None,
        }

    # -------------------------------------------------------------------------
    # 내부 헬퍼
    # -------------------------------------------------------------------------

    async def _find_or_create_dataset_group(
        self,
        name: str,
        dataset_type: str,
        annotation_format: str,
        task_types: list[str] | None = None,
    ) -> DatasetGroup:
        """
        이름 + dataset_type으로 기존 그룹을 찾고, 없으면 새로 생성한다.
        소프트 삭제된 그룹은 무시한다.
        기존 그룹이 있고 task_types가 비어 있으면, 전달된 task_types로 업데이트한다.
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
            # 기존 그룹에 task_types가 없으면 소스 교집합으로 채운다
            if not existing_group.task_types and task_types:
                existing_group.task_types = task_types
                logger.info(
                    "기존 DatasetGroup task_types 자동 설정",
                    group_id=existing_group.id,
                    task_types=task_types,
                )
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
            task_types=task_types,
        )
        self.db.add(new_group)
        await self.db.flush()
        logger.info(
            "신규 DatasetGroup 생성",
            group_id=new_group.id, group_name=new_group.name,
            task_types=task_types,
        )
        return new_group

    async def _intersect_source_task_types(
        self, config: PipelineConfig,
    ) -> list[str] | None:
        """
        파이프라인 config에서 소스 데이터셋들의 그룹을 조회하고,
        각 그룹의 task_types 교집합을 반환한다.

        소스가 없거나 교집합이 �어 있으면 None을 반환한다.
        """
        # 모든 태스크 + passthrough 에서 소스 데이터셋 ID 수집
        source_dataset_ids: set[str] = set(config.get_all_source_dataset_ids())

        if not source_dataset_ids:
            return None

        # 소스 데이터셋들의 그룹 task_types 조회
        result = await self.db.execute(
            select(DatasetGroup.task_types)
            .join(Dataset, Dataset.group_id == DatasetGroup.id)
            .where(Dataset.id.in_(source_dataset_ids))
            .distinct()
        )
        all_task_types_rows = result.scalars().all()

        # 교집합 계산
        intersection: set[str] | None = None
        for task_types_row in all_task_types_rows:
            if not task_types_row:
                continue
            current_set = set(task_types_row)
            if intersection is None:
                intersection = current_set
            else:
                intersection &= current_set

        if not intersection:
            return None

        return sorted(intersection)

    async def _next_version(self, group_id: str, split: str) -> str:
        """
        해당 group+split의 다음 버전을 자동 계산한다.

        버전 정책: {major}.{minor}
        - major: 사용자가 명시적으로 파이프라인을 실행할 때 증가
        - minor: 향후 automation이 파이프라인을 자동 실행할 때 증가 (미구현)
        파이프라인 실행은 사용자 주도이므로 major를 올린다.
        """
        result = await self.db.execute(
            select(Dataset.version)
            .where(Dataset.group_id == group_id, Dataset.split == split.upper())
            .order_by(Dataset.created_at.desc())
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
