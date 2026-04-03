"""
파이프라인 실행 엔진.

PipelineConfig를 받아서:
1. 소스 데이터셋의 annotation을 로드
2. PER_SOURCE manipulator 순차 적용
3. (다중 소스일 경우) merge
4. POST_MERGE manipulator 순차 적용
5. 이미지 복사/변환 실행
6. 출력 annotation 파일 작성
7. DB에 output DatasetGroup + Dataset + Lineage 생성

이미지 I/O는 lazy하게 수행한다 — annotation 처리가 완료된 후
ImagePlan을 기반으로 실제 파일 복사/변환을 진행한다.

이 모듈은 app/ 레이어에 의존하지 않는다.
StorageProtocol을 통해 스토리지 접근을 추상화한다.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from lib.manipulators import MANIPULATOR_REGISTRY
from lib.pipeline.config import ManipulatorConfig, PipelineConfig, SourceConfig
from lib.pipeline.image_executor import ImageExecutor
from lib.pipeline.io.coco_io import parse_coco_json, write_coco_json
from lib.pipeline.io.yolo_io import parse_yolo_dir, write_yolo_dir
from lib.pipeline.models import Annotation, DatasetMeta, DatasetPlan, ImagePlan, ImageRecord
from lib.pipeline.storage_protocol import StorageProtocol

logger = logging.getLogger(__name__)


class PipelineExecutor:
    """
    파이프라인 실행 엔진.

    Annotation 처리(Phase A)와 이미지 실행(Phase B)을 분리한다.
    Phase A: 빠름 — annotation JSON만 메모리에서 변환
    Phase B: 느림 — 이미지 파일 복사/변환 (lazy)

    Args:
        storage: StorageProtocol 구현체 (경로 해석, 파일 존재 확인 등)
        images_dirname: 이미지 서브디렉토리 이름 (기본: "images")
    """

    def __init__(
        self,
        storage: StorageProtocol,
        images_dirname: str = "images",
    ) -> None:
        self.storage = storage
        self.images_dirname = images_dirname

    def run(self, config: PipelineConfig) -> PipelineResult:
        """
        파이프라인 전체 실행.

        Args:
            config: 파이프라인 설정 (소스, manipulators, 출력 설정)

        Returns:
            PipelineResult: 실행 결과 (output_meta, output_storage_uri 등)
        """
        logger.info(
            "파이프라인 실행 시작",
            sources=len(config.sources),
            post_merge=len(config.post_merge_manipulators),
            output_group=config.output_group_name,
        )

        # ── Phase A: Annotation 처리 ──
        # 1. 소스 데이터셋별 annotation 로드 + PER_SOURCE manipulator 적용
        processed_metas: list[DatasetMeta] = []
        source_storage_uris: list[str] = []  # 이미지 복사용 원본 경로

        for source_config in config.sources:
            source_meta = self._load_source_meta(source_config.dataset_id)
            source_storage_uris.append(source_meta.storage_uri)
            logger.info(
                "소스 로드 완료",
                dataset_id=source_config.dataset_id,
                images=source_meta.image_count,
                format=source_meta.annotation_format,
            )

            # PER_SOURCE manipulator 순차 적용
            current_meta = source_meta
            for manipulator_config in source_config.manipulators:
                current_meta = self._apply_manipulator(current_meta, manipulator_config)

            processed_metas.append(current_meta)

        # 2. 다중 소스 merge (현재는 단순 concat — merge manipulator 구현 시 확장)
        if len(processed_metas) == 1:
            merged_meta = processed_metas[0]
        else:
            merged_meta = self._merge_metas(processed_metas)

        # 3. POST_MERGE manipulator 순차 적용
        output_meta = merged_meta
        for manipulator_config in config.post_merge_manipulators:
            output_meta = self._apply_manipulator(output_meta, manipulator_config)

        # 출력 포맷 결정
        output_format = config.output_annotation_format or output_meta.annotation_format
        output_meta.annotation_format = output_format

        logger.info(
            "Phase A 완료 (annotation 처리)",
            output_images=output_meta.image_count,
            output_categories=len(output_meta.categories),
            output_format=output_format,
        )

        # ── Phase B: 출력 경로 결정 + 이미지 복사 + annotation 파일 작성 ──
        output_dataset_type = config.output_dataset_type.upper()
        output_split = config.output_splits[0] if config.output_splits else "NONE"

        # storage_uri 생성
        output_storage_uri = self.storage.build_dataset_uri(
            dataset_type=output_dataset_type,
            name=config.output_group_name,
            split=output_split,
            version="v1.0.0",
        )
        output_meta.storage_uri = output_storage_uri

        # 출력 디렉토리 생성
        self.storage.makedirs(output_storage_uri)

        # 이미지 복사 계획 생성 + 실행
        image_plans = self._build_image_plans(
            output_meta, source_storage_uris, output_storage_uri,
        )
        dataset_plan = DatasetPlan(output_meta=output_meta, image_plans=image_plans)

        logger.info(
            "이미지 처리 계획",
            total=dataset_plan.total_images,
            copy_only=dataset_plan.copy_only_count,
            transform=dataset_plan.transform_count,
        )

        image_executor = ImageExecutor(self.storage)
        copied_count = image_executor.execute(dataset_plan)

        # annotation 파일 작성
        annotation_filenames = self._write_annotations(output_meta, output_storage_uri)

        # meta file (yaml) 생성 — YOLO 출력인 경우
        annotation_meta_filename: str | None = None
        if output_format.upper() == "YOLO":
            annotations_dir = self.storage.get_annotations_dir(output_storage_uri)
            from lib.pipeline.io.yolo_io import _write_data_yaml
            sorted_categories = sorted(output_meta.categories, key=lambda c: c["id"])
            _write_data_yaml(sorted_categories, annotations_dir)
            annotation_meta_filename = "data.yaml"
            logger.info("YOLO data.yaml 생성 완료")

        logger.info(
            "파이프라인 실행 완료",
            output_uri=output_storage_uri,
            images=copied_count,
            annotations=len(annotation_filenames),
        )

        return PipelineResult(
            output_meta=output_meta,
            output_storage_uri=output_storage_uri,
            output_dataset_type=output_dataset_type,
            output_split=output_split,
            annotation_filenames=annotation_filenames,
            annotation_meta_filename=annotation_meta_filename,
            image_count=copied_count,
            source_dataset_ids=[s.dataset_id for s in config.sources],
        )

    # -------------------------------------------------------------------------
    # 내부 헬퍼
    # -------------------------------------------------------------------------

    def _load_source_meta(self, dataset_id: str) -> DatasetMeta:
        """
        DB에 등록된 데이터셋의 annotation을 파싱하여 DatasetMeta로 반환.
        storage_uri + annotation_files 정보로 파일 위치를 결정한다.

        현재는 DB를 직접 조회하지 않고, storage에서 파일 기반으로 로드한다.
        (CLI 테스트용 — 추후 DB 조회 연동)
        """
        raise NotImplementedError(
            "_load_source_meta는 서브클래스 또는 외부에서 주입해야 합니다. "
            "CLI 테스트에서는 load_source_meta_from_storage()를 사용하세요."
        )

    def _apply_manipulator(
        self, meta: DatasetMeta, manipulator_config: ManipulatorConfig
    ) -> DatasetMeta:
        """단일 manipulator를 DatasetMeta에 적용한다."""
        manipulator_name = manipulator_config.manipulator_name
        manipulator_class = MANIPULATOR_REGISTRY.get(manipulator_name)
        if manipulator_class is None:
            raise ValueError(f"등록되지 않은 manipulator: {manipulator_name}")

        manipulator_instance = manipulator_class()
        result_meta = manipulator_instance.transform_annotation(
            meta, manipulator_config.params,
        )
        logger.info(
            "manipulator 적용 완료",
            name=manipulator_name,
            input_images=meta.image_count,
            output_images=result_meta.image_count,
        )
        return result_meta

    def _merge_metas(self, metas: list[DatasetMeta]) -> DatasetMeta:
        """
        다중 소스 DatasetMeta를 단순 병합한다.
        image_id 충돌 방지를 위해 재번호 매김.
        categories는 union (동일 name이면 동일 id 유지).
        """
        if not metas:
            raise ValueError("병합할 DatasetMeta가 없습니다.")

        # categories 통합 (name 기준 dedup)
        merged_categories: list[dict[str, Any]] = []
        category_name_to_id: dict[str, int] = {}
        next_category_id = 0

        for meta in metas:
            for category in meta.categories:
                if category["name"] not in category_name_to_id:
                    category_name_to_id[category["name"]] = next_category_id
                    merged_categories.append({
                        "id": next_category_id,
                        "name": category["name"],
                    })
                    next_category_id += 1

        # image_records 통합 (image_id 재번호)
        merged_records = []
        image_id_counter = 1
        for meta in metas:
            # category_id 리매핑 (원본 id → 통합 id)
            old_to_new_cat: dict[int, int] = {}
            for category in meta.categories:
                old_to_new_cat[category["id"]] = category_name_to_id[category["name"]]

            for record in meta.image_records:
                new_record = ImageRecord(
                    image_id=image_id_counter,
                    file_name=record.file_name,
                    width=record.width,
                    height=record.height,
                    annotations=[],
                    extra=record.extra,
                )
                for annotation in record.annotations:
                    new_annotation = Annotation(
                        annotation_type=annotation.annotation_type,
                        category_id=old_to_new_cat.get(
                            annotation.category_id, annotation.category_id
                        ),
                        bbox=annotation.bbox,
                        segmentation=annotation.segmentation,
                        label=annotation.label,
                        attributes=annotation.attributes,
                        extra=annotation.extra,
                    )
                    new_record.annotations.append(new_annotation)
                merged_records.append(new_record)
                image_id_counter += 1

        return DatasetMeta(
            dataset_id="",
            storage_uri="",
            annotation_format=metas[0].annotation_format,
            categories=merged_categories,
            image_records=merged_records,
        )

    def _build_image_plans(
        self,
        output_meta: DatasetMeta,
        source_storage_uris: list[str],
        output_storage_uri: str,
    ) -> list[ImagePlan]:
        """
        output_meta의 image_records로부터 이미지 복사 계획을 생성.

        현재는 단순 복사만 지원 (format_convert는 이미지 변환 불필요).
        각 이미지가 어느 소스에서 왔는지 file_name 기반으로 탐색한다.
        """
        plans: list[ImagePlan] = []

        for record in output_meta.image_records:
            # 소스 이미지 경로 탐색: 각 소스 storage_uri의 images/ 하위에서 찾기
            src_uri: str | None = None
            for source_uri in source_storage_uris:
                candidate = f"{source_uri}/{self.images_dirname}/{record.file_name}"
                if self.storage.exists(candidate):
                    src_uri = candidate
                    break

            if src_uri is None:
                logger.warning(
                    "소스 이미지를 찾을 수 없음 (건너뜀)",
                    file_name=record.file_name,
                )
                continue

            dst_uri = f"{output_storage_uri}/{self.images_dirname}/{record.file_name}"
            plans.append(ImagePlan(src_uri=src_uri, dst_uri=dst_uri))

        return plans

    def _write_annotations(
        self, output_meta: DatasetMeta, output_storage_uri: str
    ) -> list[str]:
        """
        output_meta를 포맷에 맞는 annotation 파일로 작성한다.

        Returns:
            작성된 annotation 파일명 리스트
        """
        annotations_dir = self.storage.get_annotations_dir(output_storage_uri)
        annotations_dir.mkdir(parents=True, exist_ok=True)
        output_format = output_meta.annotation_format.upper()

        if output_format == "COCO":
            output_path = annotations_dir / "instances.json"
            write_coco_json(output_meta, output_path)
            logger.info("COCO annotation 작성 완료", path=str(output_path))
            return ["instances.json"]

        elif output_format == "YOLO":
            write_yolo_dir(output_meta, annotations_dir)
            # YOLO는 이미지별 .txt + classes.txt + data.yaml
            label_files = sorted(
                f.name for f in annotations_dir.glob("*.txt")
            )
            logger.info("YOLO annotation 작성 완료", file_count=len(label_files))
            return label_files

        else:
            raise ValueError(f"지원하지 않는 출력 포맷: {output_format}")


# ─── Pipeline 실행 결과 ───

class PipelineResult:
    """파이프라인 실행 결과를 담는 컨테이너."""

    def __init__(
        self,
        output_meta: DatasetMeta,
        output_storage_uri: str,
        output_dataset_type: str,
        output_split: str,
        annotation_filenames: list[str],
        annotation_meta_filename: str | None,
        image_count: int,
        source_dataset_ids: list[str],
    ) -> None:
        self.output_meta = output_meta
        self.output_storage_uri = output_storage_uri
        self.output_dataset_type = output_dataset_type
        self.output_split = output_split
        self.annotation_filenames = annotation_filenames
        self.annotation_meta_filename = annotation_meta_filename
        self.image_count = image_count
        self.source_dataset_ids = source_dataset_ids


def load_source_meta_from_storage(
    storage: StorageProtocol,
    storage_uri: str,
    annotation_format: str,
    annotation_files: list[str],
    annotation_meta_file: str | None = None,
    dataset_id: str = "",
) -> DatasetMeta:
    """
    스토리지에 저장된 데이터셋의 annotation을 파싱하여 DatasetMeta로 반환.
    DB 없이 파일 기반으로 로드한다 (CLI 테스트용 + 파이프라인 실행용).

    Args:
        storage: StorageProtocol 구현체
        storage_uri: 데이터셋 상대경로 (예: "raw/coco8/train/v1.0.0")
        annotation_format: COCO | YOLO
        annotation_files: 어노테이션 파일명 리스트
        annotation_meta_file: 메타 파일명 (예: data.yaml)
        dataset_id: DatasetMeta.dataset_id

    Returns:
        파싱된 DatasetMeta
    """
    annotations_dir = storage.get_annotations_dir(storage_uri)
    images_dir = storage.get_images_path(storage_uri)
    format_upper = annotation_format.upper()

    if format_upper == "COCO":
        # COCO: 첫 번째 JSON 파일 파싱
        json_path = annotations_dir / annotation_files[0]
        meta = parse_coco_json(json_path, dataset_id=dataset_id, storage_uri=storage_uri)
        return meta

    elif format_upper == "YOLO":
        # YOLO: annotations 디렉토리의 .txt 파일 파싱
        yaml_path: Path | None = None
        if annotation_meta_file:
            yaml_path = annotations_dir / annotation_meta_file

        # 이미지 크기 읽기
        image_sizes: dict[str, tuple[int, int]] = {}
        if images_dir.exists():
            try:
                from PIL import Image
                for img_path in images_dir.iterdir():
                    if img_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
                        with Image.open(img_path) as img:
                            image_sizes[img_path.stem] = (img.width, img.height)
            except ImportError:
                logger.warning("Pillow가 없어 이미지 크기를 읽을 수 없습니다.")

        meta = parse_yolo_dir(
            label_dir=annotations_dir,
            image_dir=images_dir if images_dir.exists() else None,
            image_sizes=image_sizes if image_sizes else None,
            yaml_path=yaml_path,
            dataset_id=dataset_id,
            storage_uri=storage_uri,
        )
        return meta

    else:
        raise ValueError(f"지원하지 않는 annotation 포맷: {format_upper}")
