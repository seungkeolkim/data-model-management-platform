"""
Classification 데이터셋 등록 Celery 태스크.

API 레이어가 DatasetGroup(head_schema) + Dataset(status=PROCESSING)을 먼저 만들고
이 태스크를 dispatch한다. 이 태스크는 lib.classification.ingest_classification()
을 호출하여 단일 풀 + manifest.jsonl + head_schema.json 을 생성하고 Dataset을
READY 또는 ERROR로 전이한다.

§2-8 filename identity 확정 이후 동작:
    - 이미지 identity = filename. 같은 파일명은 같은 이미지로 간주된다.
    - single-label head 에서 같은 파일명이 2개 이상 class 폴더에 등장하면
      사용자 라벨링 오류로 판정하고 warning + 해당 이미지 전체 skip 처리한다.
    - 과거의 SHA 기반 content dedup / duplicate_image_policy (FAIL/SKIP) 옵션은
      폐지됐다. 충돌은 항상 skip 으로 처리하며 policy 선택지가 사라졌다.

흐름:
    1. Dataset/Group 조회
    2. lib/classification ingest 실행
    3. 성공: status=READY, image_count, metadata.class_info 갱신
       충돌로 skip 된 이미지가 있으면 process.log 와 metadata 에 상세 목록 기록
    4. 예외: status=ERROR, 부분 생성 디렉토리 정리 + 트레이스백을 process.log 로 보존
"""
from __future__ import annotations

import datetime as _dt
import logging
import shutil
import traceback
from pathlib import Path
from typing import Any

from app.core.database import SyncSessionLocal
from app.core.storage import get_storage_client
from app.models.all_models import Dataset
from app.tasks.celery_app import celery_app
from lib.classification import (
    ClassificationHeadInput,
    FilenameCollision,
    ingest_classification,
)

logger = logging.getLogger(__name__)

# dest_root 안에 남겨둘 디버깅 로그 파일명. 실패 시 원인 파악용으로 dest 정리 과정에서도 보존한다.
PROCESS_LOG_FILENAME = "process.log"


def _write_process_log(dest_abs: Path, lines: list[str]) -> Path | None:
    """dest_abs 하위에 process.log를 한 번에 기록. dest_abs가 없으면 생성한다.

    반환: 기록한 로그 파일의 절대경로. 실패하면 None.
    """
    try:
        dest_abs.mkdir(parents=True, exist_ok=True)
        log_path = dest_abs / PROCESS_LOG_FILENAME
        timestamp = _dt.datetime.now().isoformat(timespec="seconds")
        header = f"[{timestamp}] classification ingest process log"
        log_path.write_text(
            header + "\n" + "\n".join(lines) + "\n",
            encoding="utf-8",
        )
        return log_path
    except Exception as log_error:  # noqa: BLE001 — 로그 기록 실패는 원인 파악 정보 손실이지만 태스크를 죽일 이유는 없음
        logger.error("process.log 기록 실패: %s", str(log_error))
        return None


def _purge_dest_except_log(dest_abs: Path) -> None:
    """dest_abs 내용물 중 process.log만 남기고 모두 삭제. 실패 복구 중 안전하게 호출 가능.

    기존 로직처럼 dest_abs 자체를 통째로 rmtree하면 남겨둔 process.log까지 사라지므로,
    자식 엔트리 단위로 삭제한다.
    """
    if not dest_abs.exists() or not dest_abs.is_dir():
        return
    for entry in dest_abs.iterdir():
        if entry.name == PROCESS_LOG_FILENAME:
            continue
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
        except Exception as purge_error:  # noqa: BLE001
            logger.warning("dest 정리 중 일부 실패 (%s): %s", entry, str(purge_error))


def _format_skipped_collision_lines(
    skipped_collisions: list[FilenameCollision],
) -> list[str]:
    """파일명 충돌로 skip 된 이미지 상세를 사람이 읽을 process.log 라인 목록으로 변환."""
    lines: list[str] = [
        f"result: READY_WITH_SKIPS (skipped={len(skipped_collisions)})",
        "",
        "── 같은 파일명이 single-label head 의 2개 이상 class 폴더에 존재하여 skip 된 이미지 ──",
        "",
    ]
    for collision in skipped_collisions:
        classes = ", ".join(collision.conflicting_classes)
        lines.append(
            f"- head='{collision.head_name}' filename='{collision.filename}' "
            f"classes=[{classes}]"
        )
        for abs_path in collision.source_abs_paths:
            lines.append(f"    {abs_path}")
        lines.append("")
    lines.append(
        "원인: single-label head 에서 동일 파일명을 여러 class 로 라벨링한 것은 "
        "사용자 라벨링 오류입니다. 해당 이미지는 pool/manifest 에서 제외됩니다."
    )
    lines.append(
        "조치: 위 경로 중 올바른 class 의 파일만 남기고 나머지를 정리한 뒤 재등록하세요."
    )
    return lines


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
) -> dict:
    """
    Classification 데이터셋 ingest를 실행한다.

    Args:
        dataset_id: Dataset.id (UUID 문자열)
        storage_uri: 저장 대상 상대 URI (예: raw/hardhat/val/v1.0)
        heads_payload: ClassificationHeadSpec 직렬화 결과 리스트.
            [{"name", "multi_label", "classes": [...],
              "source_class_paths": [...]}]
    """
    db = SyncSessionLocal()
    try:
        return _execute_classification_register(
            db=db,
            dataset_id=dataset_id,
            storage_uri=storage_uri,
            heads_payload=heads_payload,
        )
    finally:
        db.close()


def _execute_classification_register(
    db,
    dataset_id: str,
    storage_uri: str,
    heads_payload: list[dict[str, Any]],
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
        "Classification 등록 시작: dataset_id=%s, storage_uri=%s",
        dataset_id, storage_uri,
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
        )

        # Dataset 후속 업데이트: READY + image_count + metadata.class_info
        class_info_heads = []
        for head in heads_input:
            counts = result.head_class_counts[head.name]
            # per_class_image_count 는 frontend 규약상 class_name → count 매핑 (dict).
            # ingest 는 class 순서별 list[int] 로 반환하므로 여기서 dict 로 변환한다.
            per_class_image_count = {
                class_name: counts[class_idx]
                for class_idx, class_name in enumerate(head.classes)
            }
            class_info_heads.append({
                "name": head.name,
                "multi_label": head.multi_label,
                # manifest와 동일한 순서로 class_mapping 저장
                "class_mapping": {
                    str(idx): class_name
                    for idx, class_name in enumerate(head.classes)
                },
                "per_class_image_count": per_class_image_count,
            })

        # skip 된 파일명 충돌 상세 — metadata 와 process.log 양쪽에 보존.
        skipped_detail: list[dict[str, Any]] = [
            {
                "filename": collision.filename,
                "head_name": collision.head_name,
                "conflicting_classes": collision.conflicting_classes,
                "source_abs_paths": collision.source_abs_paths,
            }
            for collision in result.skipped_collisions
        ]

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
                "skipped_collision_count": len(result.skipped_collisions),
                "skipped_collisions": skipped_detail,
            }
        }
        db.commit()

        # 충돌로 skip 된 이미지가 있으면 process.log 에 상세 목록을 남긴다.
        if result.skipped_collisions:
            _write_process_log(
                dest_abs,
                _format_skipped_collision_lines(result.skipped_collisions),
            )

        logger.info(
            "Classification 등록 완료: dataset_id=%s, images=%d, skipped_collisions=%d",
            dataset_id,
            result.image_count,
            len(result.skipped_collisions),
        )
        return {
            "status": "READY",
            "dataset_id": dataset_id,
            "image_count": result.image_count,
            "skipped_collision_count": len(result.skipped_collisions),
        }

    except Exception as exc:
        db.rollback()
        logger.error(
            "Classification 등록 실패: dataset_id=%s, error=%s",
            dataset_id, str(exc), exc_info=True,
        )
        # 알 수 없는 오류도 process.log에 트레이스백까지 남긴다.
        log_lines = [
            "result: FAILED",
            "error_kind: UNEXPECTED",
            f"exception: {type(exc).__name__}: {exc}",
            "",
            "traceback:",
            *traceback.format_exc().splitlines(),
            "",
            "입력 요약:",
            f"  storage_uri: {storage_uri}",
            *[
                f"  head '{head['name']}' multi_label={bool(head['multi_label'])} "
                f"classes={head['classes']}"
                for head in heads_payload
            ],
        ]
        log_path = _write_process_log(dest_abs, log_lines)
        _purge_dest_except_log(dest_abs)

        try:
            dataset = db.query(Dataset).filter_by(id=dataset_id).one()
            dataset.status = "ERROR"
            dataset.metadata_ = {
                "error": {
                    "kind": "UNEXPECTED",
                    "message": str(exc)[:500],
                    "process_log_relpath": (
                        PROCESS_LOG_FILENAME if log_path is not None else None
                    ),
                    "storage_uri": storage_uri,
                }
            }
            db.commit()
        except Exception as db_error:
            logger.error("에러 상태 기록 실패: %s", str(db_error))
            db.rollback()
        return {
            "status": "ERROR",
            "dataset_id": dataset_id,
            "error": str(exc)[:500],
            "process_log_relpath": PROCESS_LOG_FILENAME if log_path is not None else None,
        }
