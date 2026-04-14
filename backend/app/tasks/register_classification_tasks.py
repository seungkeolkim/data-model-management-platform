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

import datetime as _dt
import logging
import shutil
import traceback
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.database import SyncSessionLocal
from app.core.storage import get_storage_client
from app.models.all_models import Dataset, DatasetGroup
from app.tasks.celery_app import celery_app
from lib.classification import (
    ClassificationHeadInput,
    DuplicateConflict,
    DuplicateConflictError,
    IntraClassDuplicate,
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


def _format_conflict_occurrences(conflict: DuplicateConflict) -> list[str]:
    """충돌이 발생한 (class, 원본 파일명, 원본 절대경로) 쌍을 사람이 읽을 형태로 나열.

    파일명이 양쪽에서 서로 다를 수 있으므로 모두 노출한다.
    """
    lines: list[str] = []
    for occ in conflict.occurrences:
        lines.append(
            f"    class '{occ.class_name}' ← {occ.original_filename}  ({occ.source_abs_path})"
        )
    return lines


def _format_duplicate_conflict_lines(
    conflict: DuplicateConflict,
    heads_payload: list[dict[str, Any]],
    duplicate_policy: str,
) -> list[str]:
    """DuplicateConflict → 사람이 읽을 process.log 라인 목록."""
    classes = ", ".join(conflict.conflicting_classes)
    return [
        "result: FAILED",
        "error_kind: DUPLICATE_IMAGE_CONFLICT",
        f"duplicate_policy: {duplicate_policy}",
        f"head_name: {conflict.head_name}",
        f"conflicting_classes: [{classes}]",
        f"sha: {conflict.sha}",
        "",
        "원인:",
        f"  head '{conflict.head_name}'은 single-label 설정인데 내용이 동일한 이미지"
        f"(sha={conflict.sha[:12]}...)가 여러 class 폴더에 존재합니다.",
        "  동일한 바이트 내용이면 파일명이 달라도 같은 이미지로 판정됩니다.",
        "  정책이 FAIL이라 ingest를 중단했습니다.",
        "",
        "동일 이미지가 발견된 위치 (class / 파일명 / 절대경로):",
        *_format_conflict_occurrences(conflict),
        "",
        "조치 방법:",
        "  1) 위 경로의 중복 파일을 한 쪽으로만 정리한 뒤 다시 등록하거나",
        "  2) 등록 모달에서 중복 정책을 'SKIP(해당 이미지 스킵)'으로 바꿔 다시 시도하세요.",
        "     SKIP 모드는 충돌 이미지를 양쪽 모두에서 제외하고 진행합니다.",
        "",
        "입력 요약:",
        *[
            f"  - head '{head['name']}' multi_label={bool(head['multi_label'])} "
            f"classes={head['classes']}"
            for head in heads_payload
        ],
    ]


def _format_skipped_conflict_lines(
    skipped_conflicts: list[DuplicateConflict],
    intra_class_duplicates: list[IntraClassDuplicate],
) -> list[str]:
    """SKIP 정책으로 제외된 이미지 + 같은 class 내 중복 경고를 한 로그로 합쳐 작성."""
    lines: list[str] = [
        f"result: READY_WITH_SKIPS (skipped={len(skipped_conflicts)}, "
        f"intra_class_duplicates={len(intra_class_duplicates)})",
        "",
    ]
    if skipped_conflicts:
        lines.append("── 여러 class에 동시에 존재하여 양쪽에서 제외된 이미지 (duplicate_policy=SKIP) ──")
        lines.append("")
        for conflict in skipped_conflicts:
            classes = ", ".join(conflict.conflicting_classes)
            lines.append(
                f"- head='{conflict.head_name}' classes=[{classes}] sha={conflict.sha[:12]}..."
            )
            lines.extend(_format_conflict_occurrences(conflict))
            lines.append("")
    if intra_class_duplicates:
        lines.append(
            "── 같은 (head, class) 폴더 내 동일 이미지 경고 — pool에는 첫 파일 1개만 저장됨 ──"
        )
        lines.append("")
        for dup in intra_class_duplicates:
            lines.append(
                f"- head='{dup.head_name}' class='{dup.class_name}' sha={dup.sha[:12]}... "
                f"발견 {len(dup.filenames)}개:"
            )
            for filename, abs_path in zip(dup.filenames, dup.source_abs_paths):
                lines.append(f"    {filename}  ({abs_path})")
            lines.append("")
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

        # SKIP 정책으로 제외된 이미지 상세 — metadata와 process.log 양쪽에 보존.
        # 파일명이 양쪽에서 다를 수 있으므로 occurrences 전체를 기록한다.
        skipped_detail: list[dict[str, Any]] = [
            {
                "sha": conflict.sha,
                "head_name": conflict.head_name,
                "conflicting_classes": conflict.conflicting_classes,
                "occurrences": [
                    {
                        "class_name": occ.class_name,
                        "original_filename": occ.original_filename,
                        "source_abs_path": occ.source_abs_path,
                    }
                    for occ in conflict.occurrences
                ],
            }
            for conflict in result.skipped_conflicts
        ]
        intra_class_detail: list[dict[str, Any]] = [
            {
                "sha": dup.sha,
                "head_name": dup.head_name,
                "class_name": dup.class_name,
                "filenames": dup.filenames,
                "source_abs_paths": dup.source_abs_paths,
            }
            for dup in result.intra_class_duplicates
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
                "skipped_conflict_count": len(result.skipped_conflicts),
                "skipped_conflicts": skipped_detail,
                "intra_class_duplicate_count": len(result.intra_class_duplicates),
                "intra_class_duplicates": intra_class_detail,
            }
        }
        db.commit()

        # 스킵 또는 같은 class 내 중복이 있으면 process.log에 상세 목록을 남긴다.
        if result.skipped_conflicts or result.intra_class_duplicates:
            _write_process_log(
                dest_abs,
                _format_skipped_conflict_lines(
                    result.skipped_conflicts, result.intra_class_duplicates,
                ),
            )

        logger.info(
            "Classification 등록 완료: dataset_id=%s, images=%d, skipped=%d, intra_dup=%d",
            dataset_id,
            result.image_count,
            len(result.skipped_conflicts),
            len(result.intra_class_duplicates),
        )
        return {
            "status": "READY",
            "dataset_id": dataset_id,
            "image_count": result.image_count,
            "skipped_conflict_count": len(result.skipped_conflicts),
            "intra_class_duplicate_count": len(result.intra_class_duplicates),
        }

    except DuplicateConflictError as conflict_error:
        db.rollback()
        logger.warning(
            "Classification 등록 중단 — 이미지 중복 감지: dataset_id=%s, head=%s, "
            "classes=%s, file=%s",
            dataset_id,
            conflict_error.conflict.head_name,
            conflict_error.conflict.conflicting_classes,
            conflict_error.conflict.sample_original_filename,
        )
        # 사용자가 원인을 추적할 수 있도록 process.log를 먼저 기록하고, 그 외 산출물은 정리한다.
        log_lines = _format_duplicate_conflict_lines(
            conflict_error.conflict, heads_payload, duplicate_policy,
        )
        log_path = _write_process_log(dest_abs, log_lines)
        _purge_dest_except_log(dest_abs)

        try:
            dataset = db.query(Dataset).filter_by(id=dataset_id).one()
            dataset.status = "ERROR"
            dataset.metadata_ = {
                "error": {
                    "kind": "DUPLICATE_IMAGE_CONFLICT",
                    "head_name": conflict_error.conflict.head_name,
                    "conflicting_classes": conflict_error.conflict.conflicting_classes,
                    "sha": conflict_error.conflict.sha,
                    "occurrences": [
                        {
                            "class_name": occ.class_name,
                            "original_filename": occ.original_filename,
                            "source_abs_path": occ.source_abs_path,
                        }
                        for occ in conflict_error.conflict.occurrences
                    ],
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
            "error": str(conflict_error)[:500],
            "error_kind": "DUPLICATE_IMAGE_CONFLICT",
            "process_log_relpath": PROCESS_LOG_FILENAME if log_path is not None else None,
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
            f"  duplicate_policy: {duplicate_policy}",
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
