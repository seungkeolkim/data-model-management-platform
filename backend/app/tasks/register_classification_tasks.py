"""
Classification 데이터셋 등록 Celery 태스크.

API 레이어가 DatasetGroup(head_schema) + Dataset(status=PROCESSING)을 먼저 만들고
이 태스크를 dispatch한다. 이 태스크는 lib.classification.ingest_classification()
을 호출하여 단일 풀 + manifest.jsonl + head_schema.json 을 생성하고 Dataset을
READY 또는 ERROR로 전이한다.

흐름:
    1. Dataset/Group 조회
    2. lib/classification ingest 실행
    3. 성공: status=READY, image_count, metadata.class_info 갱신
    4. 실패: status=ERROR, 부분 생성 디렉토리 정리
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.database import SyncSessionLocal
from app.core.storage import get_storage_client
from app.models.all_models import Dataset, DatasetGroup
from app.tasks.celery_app import celery_app
from lib.classification import (
    ClassificationHeadInput,
    DuplicateConflictError,
    ingest_classification,
)

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.register_classification_tasks.register_classification_dataset",
    queue="default",
    max_retries=0,
)
def register_classification_dataset(
    self,
    dataset_id: str,
    storage_uri: str,
    heads_payload: list[dict[str, Any]],
    duplicate_policy: str,
) -> dict:
    """
    Classification 데이터셋 ingest를 실행한다.

    Args:
        dataset_id: Dataset.id (UUID 문자열)
        storage_uri: 저장 대상 상대 URI (예: raw/hardhat/val/v1.0)
        heads_payload: ClassificationHeadSpec 직렬화 결과 리스트.
            [{"name", "multi_label", "classes": [...],
              "source_class_paths": [...]}]
        duplicate_policy: "FAIL" 또는 "SKIP"
    """
    db = SyncSessionLocal()
    try:
        return _execute_classification_register(
            db=db,
            dataset_id=dataset_id,
            storage_uri=storage_uri,
            heads_payload=heads_payload,
            duplicate_policy=duplicate_policy,
        )
    finally:
        db.close()


def _execute_classification_register(
    db,
    dataset_id: str,
    storage_uri: str,
    heads_payload: list[dict[str, Any]],
    duplicate_policy: str,
) -> dict:
    dataset = db.query(Dataset).filter_by(id=dataset_id).one_or_none()
    if dataset is None:
        logger.error("Classification Dataset 조회 실패: %s", dataset_id)
        return {"status": "FAILED", "error": f"Dataset not found: {dataset_id}"}

    if dataset.status != "PROCESSING":
        logger.warning(
            "Classification Dataset 상태가 PROCESSING이 아님: %s (현재=%s)",
            dataset_id, dataset.status,
        )
        return {"status": "FAILED", "error": f"Unexpected status: {dataset.status}"}

    logger.info(
        "Classification 등록 시작: dataset_id=%s, storage_uri=%s, policy=%s",
        dataset_id, storage_uri, duplicate_policy,
    )

    storage = get_storage_client()
    dest_abs = storage.resolve_path(storage_uri)
    # ingest_classification이 dest_root를 생성한다.

    heads_input = [
        ClassificationHeadInput(
            name=head["name"],
            multi_label=bool(head["multi_label"]),
            classes=list(head["classes"]),
            source_class_paths=list(head["source_class_paths"]),
        )
        for head in heads_payload
    ]

    try:
        result = ingest_classification(
            dest_root=dest_abs,
            heads=heads_input,
            duplicate_policy=duplicate_policy,  # type: ignore[arg-type]
        )

        # Dataset 후속 업데이트: READY + image_count + metadata.class_info
        class_info_heads = []
        for head in heads_input:
            counts = result.head_class_counts[head.name]
            class_info_heads.append({
                "name": head.name,
                "multi_label": head.multi_label,
                # manifest와 동일한 순서로 class_mapping 저장
                "class_mapping": {
                    str(idx): class_name
                    for idx, class_name in enumerate(head.classes)
                },
                "per_class_image_count": counts,
            })

        dataset.status = "READY"
        dataset.image_count = result.image_count
        # classification은 단일 int class_count가 의미 없어 NULL 유지
        dataset.class_count = None
        dataset.annotation_format = "CLS_MANIFEST"
        dataset.annotation_files = [result.manifest_relpath]
        dataset.annotation_meta_file = result.head_schema_relpath
        dataset.metadata_ = {
            "class_info": {
                "heads": class_info_heads,
                "skipped_conflict_count": len(result.skipped_conflicts),
            }
        }
        db.commit()

        logger.info(
            "Classification 등록 완료: dataset_id=%s, images=%d, skipped=%d",
            dataset_id, result.image_count, len(result.skipped_conflicts),
        )
        return {
            "status": "READY",
            "dataset_id": dataset_id,
            "image_count": result.image_count,
            "skipped_conflict_count": len(result.skipped_conflicts),
        }

    except DuplicateConflictError as conflict_error:
        db.rollback()
        logger.warning(
            "Classification 등록 중단 — 이미지 중복 감지: dataset_id=%s, detail=%s",
            dataset_id, str(conflict_error),
        )
        if dest_abs.exists():
            shutil.rmtree(dest_abs, ignore_errors=True)
        try:
            dataset = db.query(Dataset).filter_by(id=dataset_id).one()
            dataset.status = "ERROR"
            dataset.metadata_ = {
                "error": {
                    "kind": "DUPLICATE_IMAGE_CONFLICT",
                    "head_name": conflict_error.conflict.head_name,
                    "conflicting_classes": conflict_error.conflict.conflicting_classes,
                    "sample_original_filename": conflict_error.conflict.sample_original_filename,
                }
            }
            db.commit()
        except Exception as db_error:
            logger.error("에러 상태 기록 실패: %s", str(db_error))
            db.rollback()
        return {
            "status": "ERROR",
            "dataset_id": dataset_id,
            "error": str(conflict_error)[:500],
            "error_kind": "DUPLICATE_IMAGE_CONFLICT",
        }

    except Exception as exc:
        db.rollback()
        logger.error(
            "Classification 등록 실패: dataset_id=%s, error=%s",
            dataset_id, str(exc), exc_info=True,
        )
        if dest_abs.exists():
            shutil.rmtree(dest_abs, ignore_errors=True)
        try:
            dataset = db.query(Dataset).filter_by(id=dataset_id).one()
            dataset.status = "ERROR"
            db.commit()
        except Exception as db_error:
            logger.error("에러 상태 기록 실패: %s", str(db_error))
            db.rollback()
        return {
            "status": "ERROR",
            "dataset_id": dataset_id,
            "error": str(exc)[:500],
        }
