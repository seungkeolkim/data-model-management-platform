"""
파이프라인 Celery 태스크.

Celery worker에서 실행되며, 동기 DB 세션(psycopg2)을 사용한다.

흐름:
    1. PipelineExecution 조회 → status=RUNNING
    2. Dataset.status=PROCESSING
    3. PipelineDagExecutor.run(config) 실행
    4. 성공: Dataset READY, PipelineExecution DONE, DatasetLineage 생성
    5. 실패: Dataset ERROR, PipelineExecution FAILED + error_message
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from app.core.database import SyncSessionLocal
from app.core.storage import get_storage_client
from app.models.all_models import (
    Dataset,
    DatasetGroup,
    DatasetLineage,
    PipelineExecution,
)
from app.tasks.celery_app import celery_app
from lib.pipeline.config import PipelineConfig
from lib.pipeline.dag_executor import (
    PipelineDagExecutor,
    PipelineResult,
    load_source_meta_from_storage,
)
from lib.pipeline.pipeline_data_models import DatasetMeta
from lib.pipeline.storage_protocol import StorageProtocol

logger = logging.getLogger(__name__)


class _DbAwareDagExecutor(PipelineDagExecutor):
    """
    DB 기반 소스 데이터셋 로드를 지원하는 DAG 실행기.

    Celery 태스크 내부에서 사용한다.
    sync DB 세션으로 소스 Dataset 정보를 조회하고,
    load_source_meta_from_storage()로 annotation을 파싱한다.
    """

    def __init__(self, storage: StorageProtocol, sync_db_session) -> None:
        super().__init__(storage)
        self._sync_db = sync_db_session

    def _load_source_meta(self, dataset_id: str) -> DatasetMeta:
        """DB에서 소스 데이터셋 정보를 조회하여 DatasetMeta를 로드한다."""
        source_dataset = (
            self._sync_db.query(Dataset)
            .filter(Dataset.id == dataset_id)
            .one_or_none()
        )
        if source_dataset is None:
            raise ValueError(f"소스 데이터셋을 찾을 수 없습니다: {dataset_id}")

        # annotation_files가 None이면 빈 리스트 처리
        annotation_files = source_dataset.annotation_files or []

        meta = load_source_meta_from_storage(
            storage=self.storage,
            storage_uri=source_dataset.storage_uri,
            annotation_format=source_dataset.annotation_format or "COCO",
            annotation_files=annotation_files,
            annotation_meta_file=source_dataset.annotation_meta_file,
            dataset_id=dataset_id,
        )

        # merge 파이프라인에서 파일명 prefix 생성 시 사용할 dataset_name 주입
        group = (
            self._sync_db.query(DatasetGroup)
            .filter(DatasetGroup.id == source_dataset.group_id)
            .one()
        )
        meta.extra["dataset_name"] = group.name

        return meta


@celery_app.task(
    bind=True,
    name="app.tasks.pipeline_tasks.run_pipeline",
    queue="pipeline",
    max_retries=0,  # 파이프라인은 재시도 없음 (멱등성 보장 어려움)
)
def run_pipeline(self, execution_id: str, pipeline_config: dict) -> dict:
    """
    데이터셋 파이프라인을 실행한다.

    Celery worker에서 동기적으로 실행되며, 중간 상태를 DB에 즉시 커밋한다.
    FastAPI 측의 status polling API가 이 상태를 읽어 UI에 반영한다.

    Args:
        execution_id: PipelineExecution.id (UUID 문자열)
        pipeline_config: PipelineConfig를 dict로 직렬화한 값

    Returns:
        실행 결과 요약 dict (status, image_count 등)
    """
    db = SyncSessionLocal()
    try:
        return _execute_pipeline(self, db, execution_id, pipeline_config)
    finally:
        db.close()


def _execute_pipeline(
    celery_task,
    db,
    execution_id: str,
    pipeline_config: dict,
) -> dict:
    """
    파이프라인 실행의 실제 로직.

    run_pipeline 태스크에서 호출된다.
    세션 관리 책임은 호출자(run_pipeline)에 있다.
    """
    # ── 1. PipelineExecution 조회 + RUNNING 전환 ──
    execution = db.query(PipelineExecution).filter_by(id=execution_id).one()
    execution.status = "RUNNING"
    execution.started_at = datetime.utcnow()
    execution.celery_task_id = celery_task.request.id
    execution.current_stage = "annotation_processing"
    db.commit()

    output_dataset = db.query(Dataset).filter_by(id=execution.output_dataset_id).one()
    output_dataset.status = "PROCESSING"
    db.commit()

    logger.info(
        "파이프라인 실행 시작: execution_id=%s, dataset_id=%s",
        execution_id, output_dataset.id,
    )

    try:
        # ── 2. PipelineConfig 복원 ──
        config = PipelineConfig(**pipeline_config)

        # ── 3. Executor 생성 + 실행 ──
        storage = get_storage_client()
        executor = _DbAwareDagExecutor(storage=storage, sync_db_session=db)

        # 서비스 레이어에서 사전 생성한 version 추출
        target_version = output_dataset.version
        result: PipelineResult = executor.run(config, target_version=target_version)

        # ── 4. 성공: Dataset 업데이트 ──
        output_dataset.status = "READY"
        output_dataset.storage_uri = result.output_storage_uri
        output_dataset.image_count = result.image_count
        output_dataset.class_count = len(result.output_meta.categories)
        output_dataset.annotation_files = result.annotation_filenames
        output_dataset.annotation_meta_file = result.annotation_meta_filename

        # annotation_format 확정 (변환된 경우 업데이트)
        output_dataset.annotation_format = result.output_meta.annotation_format

        # metadata 채우기: 클래스 매핑 정보 (파이프라인이 생성한 데이터는 시스템이 전부 알고 있음)
        class_mapping = {
            str(cat["id"]): cat["name"]
            for cat in result.output_meta.categories
        }
        output_dataset.metadata_ = {
            "class_info": {
                "class_count": len(result.output_meta.categories),
                "class_mapping": class_mapping,
            },
        }

        # ── 5. PipelineExecution 완료 ──
        execution.status = "DONE"
        execution.finished_at = datetime.utcnow()
        execution.current_stage = "completed"
        execution.total_count = result.image_count
        execution.processed_count = result.image_count

        # ── 6. DatasetLineage 엣지 생성 ──
        for source_dataset_id in result.source_dataset_ids:
            lineage_edge = DatasetLineage(
                id=str(uuid.uuid4()),
                parent_id=source_dataset_id,
                child_id=output_dataset.id,
                transform_config=pipeline_config,
            )
            db.add(lineage_edge)

        db.commit()

        logger.info(
            "파이프라인 실행 완료: execution_id=%s, images=%d, skipped=%d, lineage_edges=%d",
            execution_id, result.image_count, result.skipped_image_count,
            len(result.source_dataset_ids),
        )

        return {
            "status": "DONE",
            "image_count": result.image_count,
            "skipped_image_count": result.skipped_image_count,
            "output_storage_uri": result.output_storage_uri,
        }

    except Exception as exc:
        db.rollback()
        logger.error(
            "파이프라인 실행 실패: execution_id=%s, error=%s",
            execution_id, str(exc),
            exc_info=True,
        )

        # 에러 상태 기록 (새 트랜잭션)
        try:
            execution = db.query(PipelineExecution).filter_by(id=execution_id).one()
            execution.status = "FAILED"
            execution.error_message = str(exc)[:2000]
            execution.finished_at = datetime.utcnow()
            execution.current_stage = "failed"

            output_dataset = db.query(Dataset).filter_by(
                id=execution.output_dataset_id
            ).one()
            output_dataset.status = "ERROR"

            db.commit()
        except Exception as db_error:
            logger.error(
                "에러 상태 기록 실패: execution_id=%s, db_error=%s",
                execution_id, str(db_error),
            )
            db.rollback()

        return {
            "status": "FAILED",
            "error": str(exc)[:500],
        }
