"""
YAML 파이프라인 실행 스크립트.

사용법:
    cd backend && python3 run_pipeline_yaml.py pipelines/coco8_conv_coco.yaml

DB에서 source 데이터셋 정보를 조회하여 파이프라인을 실행한다.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# backend/ 루트를 sys.path에 추가
_BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND_ROOT))

# 프로젝트 루트의 .env를 dotenv로 로드 (pydantic-settings가 읽기 전에 환경변수 설정)
_PROJECT_ROOT = _BACKEND_ROOT.parent
_dotenv_path = _PROJECT_ROOT / ".env"
if _dotenv_path.exists():
    from dotenv import load_dotenv
    # override=False: 셸 환경변수가 .env보다 우선 (로컬 실행 시 경로 오버라이드 가능)
    load_dotenv(_dotenv_path, override=False)

from app.core.config import get_settings, get_app_config
from app.core.storage import get_storage_client
from lib.pipeline.config import load_pipeline_config_from_yaml
from lib.pipeline.dag_executor import PipelineDagExecutor, PipelineResult, load_source_meta_from_storage
from lib.pipeline.pipeline_data_models import DatasetMeta


def _query_dataset_info_sync(dataset_id: str) -> dict:
    """
    DB에서 dataset 정보를 동기적으로 조회한다.
    psycopg2 (sync driver)를 사용하여 Alembic과 동일한 방식으로 접속.
    """
    import psycopg2
    import json

    settings = get_settings()
    # Docker 내부 호스트명(postgres) → 로컬 접속(127.0.0.1)으로 변환
    # localhost는 IPv6(::1)로 해석될 수 있어 pg_hba 인증 실패 가능
    sync_db_url = (
        f"host=127.0.0.1 port={settings.postgres_port} "
        f"dbname={settings.postgres_db} "
        f"user={settings.postgres_user} password={settings.postgres_password}"
    )
    conn = psycopg2.connect(sync_db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.storage_uri, d.annotation_format, d.annotation_files,
                       d.annotation_meta_file, d.status, g.name as group_name
                FROM datasets d
                JOIN dataset_groups g ON d.group_id = g.id
                WHERE d.id = %s
                """,
                (dataset_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"데이터셋을 찾을 수 없습니다: {dataset_id}")

            storage_uri, annotation_format, annotation_files_raw, annotation_meta_file, status, group_name = row

            # annotation_files: JSONB → list[str]
            if isinstance(annotation_files_raw, str):
                annotation_files = json.loads(annotation_files_raw)
            elif isinstance(annotation_files_raw, list):
                annotation_files = annotation_files_raw
            else:
                annotation_files = []

            return {
                "storage_uri": storage_uri,
                "annotation_format": annotation_format,
                "annotation_files": annotation_files,
                "annotation_meta_file": annotation_meta_file,
                "status": status,
                "group_name": group_name,
            }
    finally:
        conn.close()


def run_pipeline_from_yaml(yaml_path: str) -> None:
    """YAML 파일을 읽어서 파이프라인을 실행한다."""
    # 1. YAML 파싱
    config = load_pipeline_config_from_yaml(yaml_path)
    print(f"{'='*60}")
    print(f"파이프라인 YAML 실행: {yaml_path}")
    print(f"{'='*60}")
    print(f"  name: {config.name}")
    print(f"  description: {config.description}")
    print(f"  output: {config.output.dataset_type} / {config.output.annotation_format} / {config.output.split}")
    print(f"  tasks: {list(config.tasks.keys())}")
    print(f"  실행 순서: {' → '.join(config.topological_order())}")
    print()

    # 2. source 데이터셋 정보를 DB에서 조회
    source_dataset_ids = config.get_all_source_dataset_ids()
    source_registry: dict[str, dict] = {}

    for dataset_id in source_dataset_ids:
        print(f"  [DB 조회] dataset_id={dataset_id}")
        info = _query_dataset_info_sync(dataset_id)
        print(f"    storage_uri: {info['storage_uri']}")
        print(f"    format: {info['annotation_format']}")
        print(f"    annotation_files: {len(info['annotation_files'])}개")
        print(f"    meta_file: {info['annotation_meta_file']}")
        print(f"    status: {info['status']}")
        source_registry[dataset_id] = info

    print()

    # 3. Executor 생성 (DB 조회 결과를 사용하는 서브클래스)
    storage = get_storage_client()

    class DbAwarePipelineDagExecutor(PipelineDagExecutor):
        """source_registry 기반으로 소스 메타를 로드하는 executor."""

        def _load_source_meta(self, load_dataset_id: str) -> DatasetMeta:
            source_info = source_registry.get(load_dataset_id)
            if source_info is None:
                raise ValueError(f"소스 데이터셋 정보를 찾을 수 없습니다: {load_dataset_id}")
            meta = load_source_meta_from_storage(
                storage=self.storage,
                storage_uri=source_info["storage_uri"],
                annotation_format=source_info["annotation_format"],
                annotation_files=source_info["annotation_files"],
                annotation_meta_file=source_info["annotation_meta_file"],
                dataset_id=load_dataset_id,
            )
            # merge 파이프라인에서 파일명 prefix 생성 시 사용할 dataset_name 주입
            meta.extra["dataset_name"] = source_info["group_name"]
            return meta

    executor = DbAwarePipelineDagExecutor(storage)

    # 4. 파이프라인 실행
    print("파이프라인 실행 중...")
    result = executor.run(config)

    # 5. 결과 출력
    print(f"\n{'='*60}")
    print(f"파이프라인 실행 완료!")
    print(f"{'='*60}")
    print(f"  출력 경로: {result.output_storage_uri}")
    print(f"  출력 타입: {result.output_dataset_type}")
    print(f"  출력 포맷: {result.output_format}")
    print(f"  이미지 수: {result.image_count}")
    print(f"  annotation 파일: {result.annotation_filenames}")
    print(f"  meta 파일: {result.annotation_meta_filename}")
    print(f"  categories: {len(result.output_meta.categories)}개")

    # 카테고리 상세
    for category_name in result.output_meta.categories[:10]:
        print(f"    {category_name}")
    if len(result.output_meta.categories) > 10:
        print(f"    ... ({len(result.output_meta.categories) - 10}개 더)")

    # merge 결과 상세 (file_name_mapping이 있으면 출력)
    file_name_mapping = result.output_meta.extra.get("file_name_mapping")
    if file_name_mapping:
        total_renamed = sum(len(v) for v in file_name_mapping.values())
        print(f"\n  [Merge] 파일명 rename: {total_renamed}건")
        for dataset_id, mapping in file_name_mapping.items():
            print(f"    dataset {dataset_id}:")
            for original, renamed in list(mapping.items())[:5]:
                print(f"      {original} → {renamed}")
            if len(mapping) > 5:
                print(f"      ... ({len(mapping) - 5}건 더)")

    source_ids = result.output_meta.extra.get("source_dataset_ids")
    if source_ids:
        print(f"  [Merge] 소스 데이터셋: {source_ids}")

    # 출력 파일 검증
    output_abs = storage.resolve_path(result.output_storage_uri)
    images_dir = storage.get_images_dir(result.output_storage_uri)
    ann_dir = storage.get_annotations_dir(result.output_storage_uri)

    print(f"\n  [검증] 출력 디렉토리: {output_abs}")
    print(f"  [검증] images/ 파일 수: {len(list(images_dir.iterdir())) if images_dir.exists() else 0}")
    print(f"  [검증] annotations/ 파일 수: {len(list(ann_dir.iterdir())) if ann_dir.exists() else 0}")

    # COCO JSON이면 내용 검증
    if result.output_format == "COCO":
        import json
        coco_json_path = ann_dir / "instances.json"
        if coco_json_path.exists():
            with open(coco_json_path) as f:
                coco_data = json.load(f)
            print(f"  [검증] COCO JSON — images: {len(coco_data['images'])}, "
                  f"annotations: {len(coco_data['annotations'])}, "
                  f"categories: {len(coco_data['categories'])}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python3 run_pipeline_yaml.py <yaml_path>")
        print("예: python3 run_pipeline_yaml.py pipelines/coco8_conv_coco.yaml")
        sys.exit(1)

    run_pipeline_from_yaml(sys.argv[1])
