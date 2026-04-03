"""
파이프라인 실행 CLI 테스트 (DAG 구조).

DB에 등록된 RAW YOLO 데이터셋을 읽어서
format_convert_to_coco manipulator를 적용하여
SOURCE COCO 데이터셋을 생성한다.

실행:
    cd backend && python tests/test_pipeline_cli.py

전제 조건:
    - DB에 YOLO 포맷의 RAW 데이터셋이 등록되어 있어야 함
    - LOCAL_STORAGE_BASE에 해당 데이터가 존재해야 함
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings, get_app_config
from app.core.storage import get_storage_client
from app.pipeline.executor import PipelineExecutor, PipelineResult, load_source_meta_from_storage
from app.pipeline.models import DatasetMeta, DatasetPlan, ImagePlan
from app.schemas.pipeline import PipelineConfig, TaskConfig, OutputConfig


def create_pipeline_executor_for_cli(
    source_registry: dict[str, dict],
) -> PipelineExecutor:
    """
    CLI 테스트용 PipelineExecutor를 생성한다.
    _load_source_meta를 파일 기반 로드로 오버라이드.

    Args:
        source_registry: dataset_id → {storage_uri, annotation_format, annotation_files, annotation_meta_file}
    """
    storage = get_storage_client()

    class CliPipelineExecutor(PipelineExecutor):
        """CLI 테스트용 — DB 대신 직접 지정한 소스 정보를 사용."""

        def _load_source_meta(self, load_dataset_id: str) -> DatasetMeta:
            source_info = source_registry.get(load_dataset_id)
            if source_info is None:
                raise ValueError(f"소스 데이터셋을 찾을 수 없습니다: {load_dataset_id}")
            return load_source_meta_from_storage(
                storage=self.storage,
                storage_uri=source_info["storage_uri"],
                annotation_format=source_info["annotation_format"],
                annotation_files=source_info["annotation_files"],
                annotation_meta_file=source_info["annotation_meta_file"],
                dataset_id=load_dataset_id,
            )

    return CliPipelineExecutor(storage)


def run_yolo_to_coco_pipeline() -> None:
    """RAW YOLO → SOURCE COCO 변환 파이프라인 실행."""
    storage = get_storage_client()

    # ── 소스 데이터셋 정보 (DB에 등록된 coco8/train) ──
    source_storage_uri = "raw/coco8/train/v1.0.0"
    source_format = "YOLO"

    # annotation 파일 목록 탐색
    annotations_dir = storage.get_annotations_dir(source_storage_uri)
    if not annotations_dir.exists():
        print(f"[ERROR] 소스 annotation 경로가 존재하지 않습니다: {annotations_dir}")
        print("먼저 웹 UI에서 YOLO 데이터셋을 등록하세요.")
        return

    annotation_files = sorted(
        f.name for f in annotations_dir.iterdir()
        if f.is_file() and f.suffix == ".txt" and f.name != "classes.txt"
    )
    # meta file 탐색
    annotation_meta_file: str | None = None
    for candidate in ("data.yaml", "coco8.yaml"):
        if (annotations_dir / candidate).exists():
            annotation_meta_file = candidate
            break

    print(f"{'='*60}")
    print(f"파이프라인 CLI 테스트: RAW YOLO → SOURCE COCO")
    print(f"{'='*60}")
    print(f"  소스: {source_storage_uri}")
    print(f"  포맷: {source_format}")
    print(f"  annotation 파일: {len(annotation_files)}개")
    print(f"  meta 파일: {annotation_meta_file}")
    print()

    # 가상 dataset_id
    source_dataset_id = str(uuid.uuid4())

    # DAG 기반 PipelineConfig 구성
    pipeline_config = PipelineConfig(
        name="coco8-as-coco",
        description="coco8 YOLO → COCO 변환 테스트",
        output=OutputConfig(
            dataset_type="SOURCE",
            annotation_format="COCO",
            split="TRAIN",
        ),
        tasks={
            "convert_to_coco": TaskConfig(
                operator="format_convert_to_coco",
                inputs=[f"source:{source_dataset_id}"],
                params={},
            ),
        },
    )

    # Executor 생성 및 실행
    executor = create_pipeline_executor_for_cli(
        source_registry={
            source_dataset_id: {
                "storage_uri": source_storage_uri,
                "annotation_format": source_format,
                "annotation_files": annotation_files,
                "annotation_meta_file": annotation_meta_file,
            },
        },
    )

    result = executor.run(pipeline_config)

    # 결과 출력
    print(f"\n{'='*60}")
    print(f"파이프라인 실행 완료!")
    print(f"{'='*60}")
    print(f"  출력 경로: {result.output_storage_uri}")
    print(f"  출력 타입: {result.output_dataset_type}")
    print(f"  출력 포맷: {result.output_meta.annotation_format}")
    print(f"  이미지 수: {result.image_count}")
    print(f"  annotation 파일: {result.annotation_filenames}")
    print(f"  meta 파일: {result.annotation_meta_filename}")
    print(f"  categories: {len(result.output_meta.categories)}개")
    print()

    # 출력 파일 확인
    output_abs = storage.resolve_path(result.output_storage_uri)
    images_dir = storage.get_images_path(result.output_storage_uri)
    ann_dir = storage.get_annotations_dir(result.output_storage_uri)

    print(f"  [검증] 출력 디렉토리 존재: {output_abs.exists()}")
    print(f"  [검증] images/ 파일 수: {len(list(images_dir.iterdir())) if images_dir.exists() else 0}")
    print(f"  [검증] annotations/ 파일 수: {len(list(ann_dir.iterdir())) if ann_dir.exists() else 0}")

    # COCO JSON 파싱 검증
    if ann_dir.exists():
        coco_json = ann_dir / "instances.json"
        if coco_json.exists():
            import json
            with open(coco_json) as f:
                coco_data = json.load(f)
            print(f"  [검증] COCO JSON images: {len(coco_data['images'])}")
            print(f"  [검증] COCO JSON annotations: {len(coco_data['annotations'])}")
            print(f"  [검증] COCO JSON categories: {len(coco_data['categories'])}")
            for cat in coco_data["categories"][:5]:
                print(f"    {cat['id']}: {cat['name']}")
            if len(coco_data["categories"]) > 5:
                print(f"    ... ({len(coco_data['categories']) - 5}개 더)")


def run_coco_to_yolo_pipeline() -> None:
    """SOURCE COCO → SOURCE YOLO 변환 파이프라인 실행 (roundtrip 검증)."""
    storage = get_storage_client()

    # 앞에서 생성한 COCO 데이터 사용
    source_storage_uri = "source/coco8-as-coco/train/v1.0.0"
    annotations_dir = storage.get_annotations_dir(source_storage_uri)

    if not annotations_dir.exists() or not (annotations_dir / "instances.json").exists():
        print(f"\n[SKIP] COCO → YOLO 역변환 테스트 건너뜀 (소스 없음: {source_storage_uri})")
        return

    print(f"\n{'='*60}")
    print(f"파이프라인 CLI 테스트: SOURCE COCO → SOURCE YOLO (역변환)")
    print(f"{'='*60}")

    source_dataset_id = str(uuid.uuid4())

    # DAG 기반 PipelineConfig 구성
    pipeline_config = PipelineConfig(
        name="coco8-as-yolo",
        description="coco8 COCO → YOLO 역변환 테스트",
        output=OutputConfig(
            dataset_type="SOURCE",
            annotation_format="YOLO",
            split="TRAIN",
        ),
        tasks={
            "convert_to_yolo": TaskConfig(
                operator="format_convert_to_yolo",
                inputs=[f"source:{source_dataset_id}"],
                params={},
            ),
        },
    )

    executor = create_pipeline_executor_for_cli(
        source_registry={
            source_dataset_id: {
                "storage_uri": source_storage_uri,
                "annotation_format": "COCO",
                "annotation_files": ["instances.json"],
                "annotation_meta_file": None,
            },
        },
    )

    result = executor.run(pipeline_config)

    print(f"\n  출력 경로: {result.output_storage_uri}")
    print(f"  출력 포맷: {result.output_meta.annotation_format}")
    print(f"  이미지 수: {result.image_count}")
    print(f"  meta 파일: {result.annotation_meta_filename}")
    print(f"  categories: {len(result.output_meta.categories)}개")

    # data.yaml 확인
    ann_dir = storage.get_annotations_dir(result.output_storage_uri)
    yaml_path = ann_dir / "data.yaml"
    if yaml_path.exists():
        print(f"\n  [검증] data.yaml 내용 (첫 10줄):")
        for line in yaml_path.read_text().splitlines()[:10]:
            print(f"    {line}")


if __name__ == "__main__":
    print("=" * 60)
    print("Pipeline Executor CLI Test (DAG 구조)")
    print("=" * 60)

    run_yolo_to_coco_pipeline()
    run_coco_to_yolo_pipeline()

    print(f"\n{'='*60}")
    print("전체 테스트 완료!")
    print(f"{'='*60}")
