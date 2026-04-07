"""
데이터셋 등록 Celery 태스크.

Celery worker에서 실행되며, 동기 DB 세션(psycopg2)을 사용한다.

흐름:
    1. Dataset 조회 → status가 PROCESSING인지 확인
    2. 파일 복사 (이미지 폴더 + 어노테이션 파일 + 메타 파일)
    3. 성공: Dataset READY + image_count/annotation_files 등 업데이트
    4. 실패: Dataset ERROR + 부분 생성 디렉토리 정리
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.core.config import settings
from app.core.database import SyncSessionLocal
from app.core.storage import get_storage_client
from app.models.all_models import Dataset
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.register_tasks.register_dataset",
    queue="default",
    max_retries=0,
)
def register_dataset(
    self,
    dataset_id: str,
    storage_uri: str,
    source_image_dir: str,
    source_annotation_files: list[str],
    source_annotation_meta_file: str | None,
    annotation_format: str,
) -> dict:
    """
    데이터셋 파일을 관리 스토리지로 복사한다.

    API 레이어에서 Dataset(status=PROCESSING)을 먼저 생성한 뒤 이 태스크를 dispatch한다.
    복사 완료 시 READY, 실패 시 ERROR로 상태를 전이한다.

    Args:
        dataset_id: Dataset.id (UUID 문자열)
        storage_uri: 복사 대상 storage URI (예: raw/coco128/train/v1.0.0)
        source_image_dir: 원본 이미지 디렉토리 절대 경로
        source_annotation_files: 원본 어노테이션 파일 절대 경로 리스트
        source_annotation_meta_file: 원본 메타 파일 절대 경로 (optional)
        annotation_format: 어노테이션 포맷 (COCO, YOLO 등)

    Returns:
        실행 결과 요약 dict
    """
    db = SyncSessionLocal()
    try:
        return _execute_register(
            db=db,
            dataset_id=dataset_id,
            storage_uri=storage_uri,
            source_image_dir=source_image_dir,
            source_annotation_files=source_annotation_files,
            source_annotation_meta_file=source_annotation_meta_file,
            annotation_format=annotation_format,
        )
    finally:
        db.close()


def _execute_register(
    db,
    dataset_id: str,
    storage_uri: str,
    source_image_dir: str,
    source_annotation_files: list[str],
    source_annotation_meta_file: str | None,
    annotation_format: str,
) -> dict:
    """데이터셋 등록의 실제 로직."""
    dataset = db.query(Dataset).filter_by(id=dataset_id).one_or_none()
    if dataset is None:
        logger.error("Dataset을 찾을 수 없음: %s", dataset_id)
        return {"status": "FAILED", "error": f"Dataset not found: {dataset_id}"}

    if dataset.status != "PROCESSING":
        logger.warning(
            "Dataset 상태가 PROCESSING이 아님: %s (현재: %s)", dataset_id, dataset.status
        )
        return {"status": "FAILED", "error": f"Unexpected status: {dataset.status}"}

    logger.info(
        "데이터셋 파일 복사 시작: dataset_id=%s, storage_uri=%s",
        dataset_id, storage_uri,
    )

    dest_abs = Path(settings.local_storage_base) / storage_uri
    storage = get_storage_client()

    try:
        # ── 이미지 폴더 복사 ──
        image_dir_path = Path(source_image_dir)
        image_count = storage.copy_image_directory(image_dir_path, storage_uri)
        logger.info("이미지 폴더 복사 완료: %d장", image_count)

        # ── 어노테이션 파일 복사 ──
        annotation_paths = [Path(p) for p in source_annotation_files]
        annotation_filenames = storage.copy_annotation_files(annotation_paths, storage_uri)
        logger.info("어노테이션 파일 복사 완료: %d개", len(annotation_filenames))

        # ── 메타 파일 복사 (선택사항) ──
        annotation_meta_filename: str | None = None
        if source_annotation_meta_file:
            annotation_meta_filename = storage.copy_annotation_meta_file(
                Path(source_annotation_meta_file), storage_uri
            )
            logger.info("메타 파일 복사 완료: %s", annotation_meta_filename)

        # ── Dataset 업데이트 → READY ──
        dataset.status = "READY"
        dataset.image_count = image_count
        dataset.annotation_files = annotation_filenames
        dataset.annotation_meta_file = annotation_meta_filename

        # 클래스 정보 자동 추출 (best-effort)
        if annotation_format.upper() in ("COCO", "YOLO"):
            try:
                _extract_class_info_sync(dataset, storage, annotation_format)
                logger.info("클래스 정보 자동 추출 완료: dataset_id=%s", dataset_id)
            except Exception as class_err:
                logger.warning(
                    "클래스 정보 자동 추출 실패 (등록은 정상 진행): %s", str(class_err)
                )

        db.commit()
        logger.info(
            "데이터셋 등록 완료: dataset_id=%s, images=%d", dataset_id, image_count
        )
        return {
            "status": "READY",
            "dataset_id": dataset_id,
            "image_count": image_count,
        }

    except Exception as exc:
        db.rollback()
        logger.error(
            "데이터셋 파일 복사 실패: dataset_id=%s, error=%s",
            dataset_id, str(exc), exc_info=True,
        )

        # 부분 생성된 디렉토리 정리
        if dest_abs.exists():
            shutil.rmtree(dest_abs, ignore_errors=True)
            logger.info("부분 생성 디렉토리 정리 완료: %s", str(dest_abs))

        # 에러 상태 기록
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


def _extract_class_info_sync(
    dataset: Dataset,
    storage,
    annotation_format: str,
) -> None:
    """
    동기 환경에서 클래스 정보를 추출하여 dataset에 반영.
    Celery 태스크 내부에서 호출한다.
    """
    from app.core.config import get_app_config

    app_config = get_app_config()
    dataset_path = storage.resolve_path(dataset.storage_uri)
    ann_dir = dataset_path / app_config.annotations_dirname

    fmt = annotation_format.upper()
    if fmt == "COCO":
        _extract_coco_class_info(dataset, ann_dir)
    elif fmt == "YOLO":
        _extract_yolo_class_info(dataset, dataset_path)


def _extract_coco_class_info(dataset: Dataset, annotations_dir: Path) -> None:
    """COCO JSON에서 categories를 읽어 class_info 구성."""
    import json

    annotation_files = dataset.annotation_files or []
    if not annotation_files:
        return

    # 첫 번째 COCO JSON 파일에서 categories 추출
    coco_path = annotations_dir / annotation_files[0]
    if not coco_path.exists():
        return

    with open(coco_path, "r", encoding="utf-8") as f:
        coco_data = json.load(f)

    categories = coco_data.get("categories", [])
    if not categories:
        return

    class_mapping = {str(cat["id"]): cat["name"] for cat in categories}
    dataset.class_count = len(categories)
    dataset.metadata_ = {
        "class_info": {
            "class_count": len(categories),
            "class_mapping": class_mapping,
        }
    }


def _extract_yolo_class_info(dataset: Dataset, dataset_root: Path) -> None:
    """YOLO data.yaml에서 names를 읽어 class_info 구성."""
    import yaml

    # data.yaml은 데이터셋 루트에 위치
    yaml_path = dataset_root / "data.yaml"

    # 메타 파일이 다른 이름일 수 있음
    if not yaml_path.exists() and dataset.annotation_meta_file:
        yaml_path = dataset_root / dataset.annotation_meta_file

    if not yaml_path.exists():
        return

    with open(yaml_path, "r", encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f)

    names = yaml_data.get("names", {})
    if not names:
        return

    # names가 dict면 그대로, list면 index→name 변환
    if isinstance(names, list):
        class_mapping = {str(i): name for i, name in enumerate(names)}
    else:
        class_mapping = {str(k): v for k, v in names.items()}

    dataset.class_count = len(class_mapping)
    dataset.metadata_ = {
        "class_info": {
            "class_count": len(class_mapping),
            "class_mapping": class_mapping,
        }
    }
