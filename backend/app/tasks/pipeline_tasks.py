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
    DatasetGroup,
    DatasetLineage,
    DatasetSplit,
    DatasetVersion,
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

    def __init__(
        self,
        storage: StorageProtocol,
        sync_db_session,
        on_task_progress=None,
    ) -> None:
        super().__init__(storage, on_task_progress=on_task_progress)
        self._sync_db = sync_db_session

    def _load_source_meta(self, dataset_id: str) -> DatasetMeta:
        """DB에서 소스 데이터셋 정보를 조회하여 DatasetMeta를 로드한다."""
        source_dataset = (
            self._sync_db.query(DatasetVersion)
            .filter(DatasetVersion.id == dataset_id)
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

        # merge 파이프라인에서 파일명 prefix 생성 시 사용할 dataset_name 주입.
        # v7.9: group_id 접근은 split_slot 경유 (association_proxy).
        group_id_value = source_dataset.group_id  # association_proxy 로 split_slot → group_id
        group = (
            self._sync_db.query(DatasetGroup)
            .filter(DatasetGroup.id == group_id_value)
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

    output_dataset = db.query(DatasetVersion).filter_by(id=execution.output_dataset_id).one()
    output_dataset.status = "PROCESSING"
    db.commit()

    logger.info(
        "파이프라인 실행 시작: execution_id=%s, dataset_id=%s",
        execution_id, output_dataset.id,
    )

    try:
        # ── 2. PipelineConfig 복원 ──
        config = PipelineConfig(**pipeline_config)

        # ── 2-a. pipeline.png 생성 (보험용 스냅샷, 실행 전에 저장) ──
        storage = get_storage_client()
        try:
            from lib.pipeline.pipeline_visualizer import render_pipeline_png

            # 소스 데이터셋의 그룹 이름을 조회하여 표시용 매핑 생성
            source_dataset_names: dict[str, str] = {}
            for source_id in config.get_all_source_dataset_ids():
                source_ds = db.query(DatasetVersion).filter_by(id=source_id).one_or_none()
                if source_ds:
                    # association_proxy 로 split_slot → group_id 해결.
                    group_id_value = source_ds.group_id
                    source_group = db.query(DatasetGroup).filter_by(id=group_id_value).one_or_none()
                    if source_group:
                        # association_proxy 로 split 문자열 조회.
                        split_name_value = source_ds.split
                        source_dataset_names[source_id] = (
                            f"{source_group.name}\n{split_name_value}/{source_ds.version}"
                        )

            png_output_dir = storage.resolve_path(output_dataset.storage_uri)
            png_output_dir.mkdir(parents=True, exist_ok=True)
            render_pipeline_png(
                pipeline_config=config,
                output_path=png_output_dir / "pipeline.png",
                source_dataset_names=source_dataset_names,
            )
        except Exception as png_error:
            logger.warning("pipeline.png 생성 건너뜀: %s", str(png_error))

        # ── 3. 태스크 진행 콜백 정의 ──
        # executor가 태스크 시작/완료 시 호출하면 메모리에 진행 상태를 누적한다.
        # DB commit은 최종 성공/실패 시점에 한번만 수행한다.
        # (중간 commit 시 SQLAlchemy expire_on_commit으로 인해 외부 ORM 객체가
        #  expire되어 최종 commit에서 task_progress가 누락되는 문제 방지)
        task_progress_state: dict[str, dict] = {}

        def _on_task_progress(task_name: str, status: str, detail: dict) -> None:
            """DAG 태스크 진행 콜백 — 메모리에 진행 상태를 누적한다."""
            if task_name not in task_progress_state:
                task_progress_state[task_name] = {}
            task_progress_state[task_name]["status"] = status
            task_progress_state[task_name].update(detail)

        # ── 4. Executor 생성 + 실행 ──
        executor = _DbAwareDagExecutor(
            storage=storage,
            sync_db_session=db,
            on_task_progress=_on_task_progress,
        )

        # 서비스 레이어에서 사전 생성한 version 추출
        target_version = output_dataset.version
        result: PipelineResult = executor.run(config, target_version=target_version)

        # ── 4. 성공: Dataset 업데이트 ──
        output_dataset.status = "READY"
        output_dataset.storage_uri = result.output_storage_uri
        output_dataset.image_count = result.image_count
        output_dataset.annotation_files = result.annotation_filenames
        output_dataset.annotation_meta_file = result.annotation_meta_filename
        output_dataset.annotation_format = result.output_format

        # task_kind 에 따라 class_count/metadata 작성 방식이 다르다.
        # - DETECTION: categories(list[str]) 기반 class_mapping
        # - CLASSIFICATION: head_schema(list[HeadSchema]) 기반 heads 구조
        if result.output_meta.task_kind == "CLASSIFICATION":
            head_schema = result.output_meta.head_schema or []
            # head/class 별 이미지 수를 image_records.labels 로부터 재계산 — RAW 와 동일 규약.
            per_head_class_counts: dict[str, dict[str, int]] = {
                head.name: {class_name: 0 for class_name in head.classes}
                for head in head_schema
            }
            for record in result.output_meta.image_records:
                for head_name, class_names in (record.labels or {}).items():
                    if class_names is None:
                        continue  # null = unknown (§2-12) — 카운트 대상 아님
                    head_bucket = per_head_class_counts.get(head_name)
                    if head_bucket is None:
                        continue
                    for class_name in class_names:
                        if class_name in head_bucket:
                            head_bucket[class_name] += 1
            class_info_heads = [
                {
                    "name": head.name,
                    "multi_label": head.multi_label,
                    "class_mapping": {
                        str(class_idx): class_name
                        for class_idx, class_name in enumerate(head.classes)
                    },
                    "per_class_image_count": per_head_class_counts[head.name],
                }
                for head in head_schema
            ]
            # classification 은 단일 int class_count 가 의미 없어 NULL 유지 (RAW 등록과 동일 규약).
            output_dataset.class_count = None
            output_dataset.metadata_ = {
                "class_info": {
                    "heads": class_info_heads,
                },
            }

            # ── DatasetGroup.head_schema SSOT 초기화 (setdefault 시맨틱) ──
            # 설계서 §2-8: "Group 내 모든 Dataset 은 동일 head_schema".
            # 신규 그룹에 classification 출력이 처음 들어올 때 group.head_schema
            # 가 아직 None 이면 이번 파이프라인 결과로 초기화한다. 이미 값이
            # 있는 경우(기존 그룹)는 건드리지 않음 — 불일치 여부는 실행 전
            # 정적 검증 단계에서 이미 차단되므로 여기서 재검사하지 않는다.
            if output_dataset.group is not None and output_dataset.group.head_schema is None:
                output_dataset.group.head_schema = {
                    "heads": [
                        {
                            "name": head.name,
                            "multi_label": head.multi_label,
                            "classes": list(head.classes),
                        }
                        for head in head_schema
                    ],
                }
        else:
            output_dataset.class_count = len(result.output_meta.categories)
            class_mapping = {
                str(idx): name
                for idx, name in enumerate(result.output_meta.categories)
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
        execution.task_progress = dict(task_progress_state) if task_progress_state else None

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
            execution.task_progress = dict(task_progress_state) if task_progress_state else None

            output_dataset = db.query(DatasetVersion).filter_by(
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
