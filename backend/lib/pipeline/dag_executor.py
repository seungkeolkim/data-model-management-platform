"""
파이프라인 DAG 실행 엔진.

PipelineConfig의 tasks를 topological sort하여 순서대로 실행한다.
각 태스크는 입력(source 데이터셋 또는 이전 태스크 출력)을 받아
manipulator를 적용하고 DatasetMeta를 출력한다.

실행 흐름:
    1. topological sort로 실행 순서 결정
    2. 태스크별 실행:
       a. inputs 해석 (source: → 파일 로드, 태스크명 → 이전 결과 참조)
       b. 다중 입력이면 merge
       c. operator(manipulator) 적용
    3. 최종 태스크의 DatasetMeta로 이미지 실체화 + annotation 작성

이 모듈은 app/ 레이어에 의존하지 않는다.
StorageProtocol을 통해 스토리지 접근을 추상화한다.
"""
from __future__ import annotations

import logging
from typing import Any

from lib.manipulators import MANIPULATOR_REGISTRY
from lib.pipeline.config import PipelineConfig, TaskConfig
from lib.pipeline.image_materializer import ImageMaterializer
from lib.pipeline.io.coco_io import parse_coco_json, write_coco_json
from lib.pipeline.io.yolo_io import parse_yolo_dir, write_yolo_dir
from lib.pipeline.pipeline_data_models import (
    Annotation, DatasetMeta, DatasetPlan, ImagePlan, ImageRecord,
)
from lib.pipeline.storage_protocol import StorageProtocol

logger = logging.getLogger(__name__)


class PipelineDagExecutor:
    """
    DAG 기반 파이프라인 실행 엔진.

    topological sort로 태스크 실행 순서를 결정하고,
    각 태스크의 inputs → operator 적용 → 출력을 다음 태스크에 전달한다.

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
            config: DAG 기반 파이프라인 설정

        Returns:
            PipelineResult: 실행 결과
        """
        logger.info(
            "파이프라인 실행 시작: name=%s, tasks=%d",
            config.name, len(config.tasks),
        )

        execution_order = config.topological_order()
        terminal_task_name = config.get_terminal_task_name()

        logger.info("실행 순서: %s", " → ".join(execution_order))

        # ── Phase A: DAG 태스크 순차 실행 (annotation 처리) ──
        # 태스크명 → 해당 태스크의 출력 DatasetMeta
        task_results: dict[str, DatasetMeta] = {}
        # 태스크별 source storage_uri 수집 (이미지 실체화용)
        all_source_storage_uris: list[str] = []

        for task_name in execution_order:
            task_config = config.tasks[task_name]
            logger.info(
                "태스크 실행: %s (operator=%s, inputs=%s)",
                task_name, task_config.operator, task_config.inputs,
            )

            # 입력 DatasetMeta 수집
            input_metas: list[DatasetMeta] = []

            for ref in task_config.inputs:
                if ref.startswith("source:"):
                    # 소스 데이터셋 로드
                    dataset_id = ref.split(":", 1)[1]
                    source_meta = self._load_source_meta(dataset_id)
                    all_source_storage_uris.append(source_meta.storage_uri)
                    logger.info(
                        "소스 로드 완료: dataset_id=%s, images=%d, format=%s",
                        dataset_id, source_meta.image_count,
                        source_meta.annotation_format,
                    )
                    input_metas.append(source_meta)
                else:
                    # 이전 태스크 출력 참조
                    if ref not in task_results:
                        raise RuntimeError(
                            f"태스크 '{task_name}'의 input '{ref}'가 "
                            f"아직 실행되지 않았습니다."
                        )
                    input_metas.append(task_results[ref])

            # 다중 입력이면 merge 후 manipulator 적용,
            # 단일 입력이면 바로 manipulator 적용
            if len(input_metas) == 1:
                working_meta = input_metas[0]
            else:
                working_meta = self._merge_metas(input_metas)

            # operator(manipulator) 적용
            result_meta = self._apply_manipulator(
                working_meta, task_config.operator, task_config.params,
            )
            task_results[task_name] = result_meta

            logger.info(
                "태스크 완료: %s → images=%d, categories=%d",
                task_name, result_meta.image_count, len(result_meta.categories),
            )

        # 최종 태스크의 출력이 파이프라인의 최종 결과
        output_meta = task_results[terminal_task_name]

        # 출력 포맷 결정
        output_format = config.output.annotation_format or output_meta.annotation_format
        output_meta.annotation_format = output_format

        logger.info(
            "Phase A 완료 (annotation 처리): images=%d, categories=%d, format=%s",
            output_meta.image_count, len(output_meta.categories), output_format,
        )

        # ── Phase B: 출력 경로 결정 + 이미지 실체화 + annotation 파일 작성 ──
        output_dataset_type = config.output.dataset_type.upper()
        output_split = config.output.split.upper()

        # storage_uri 생성
        output_storage_uri = self.storage.build_dataset_uri(
            dataset_type=output_dataset_type,
            name=config.name,
            split=output_split,
            version="v1.0.0",
        )
        output_meta.storage_uri = output_storage_uri

        # 출력 디렉토리 생성
        self.storage.makedirs(output_storage_uri)

        # 이미지 실체화 계획 생성 + 실행
        image_plans = self._build_image_plans(
            output_meta, all_source_storage_uris, output_storage_uri,
        )
        dataset_plan = DatasetPlan(output_meta=output_meta, image_plans=image_plans)

        logger.info(
            "이미지 실체화 계획: total=%d, copy_only=%d, transform=%d",
            dataset_plan.total_images, dataset_plan.copy_only_count,
            dataset_plan.transform_count,
        )

        image_materializer = ImageMaterializer(self.storage)
        materialized_count = image_materializer.materialize(dataset_plan)

        # annotation 파일 작성
        annotation_filenames = self._write_annotations(output_meta, output_storage_uri)

        # meta file (yaml) 생성 — YOLO 출력인 경우
        annotation_meta_filename: str | None = None
        if output_format.upper() == "YOLO":
            annotations_dir = self.storage.get_annotations_dir(output_storage_uri)
            from lib.pipeline.io.yolo_io import _write_yolo_data_yaml
            sorted_categories = sorted(output_meta.categories, key=lambda c: c["id"])
            _write_yolo_data_yaml(sorted_categories, annotations_dir)
            annotation_meta_filename = "data.yaml"
            logger.info("YOLO data.yaml 생성 완료")

        logger.info(
            "파이프라인 실행 완료: output_uri=%s, images=%d, annotations=%d",
            output_storage_uri, materialized_count, len(annotation_filenames),
        )

        return PipelineResult(
            output_meta=output_meta,
            output_storage_uri=output_storage_uri,
            output_dataset_type=output_dataset_type,
            output_split=output_split,
            annotation_filenames=annotation_filenames,
            annotation_meta_filename=annotation_meta_filename,
            image_count=materialized_count,
            source_dataset_ids=config.get_all_source_dataset_ids(),
        )

    # -------------------------------------------------------------------------
    # 내부 헬퍼
    # -------------------------------------------------------------------------

    def _load_source_meta(self, dataset_id: str) -> DatasetMeta:
        """
        DB에 등록된 데이터셋의 annotation을 파싱하여 DatasetMeta로 반환.
        서브클래스에서 오버라이드하여 DB/파일 기반 로드를 구현한다.
        """
        raise NotImplementedError(
            "_load_source_meta는 서브클래스에서 오버라이드해야 합니다. "
            "CLI 테스트에서는 load_source_meta_from_storage()를 사용하세요."
        )

    def _apply_manipulator(
        self,
        meta: DatasetMeta,
        operator_name: str,
        params: dict[str, Any],
    ) -> DatasetMeta:
        """단일 manipulator(operator)를 DatasetMeta에 적용한다."""
        manipulator_class = MANIPULATOR_REGISTRY.get(operator_name)
        if manipulator_class is None:
            raise ValueError(f"등록되지 않은 manipulator: {operator_name}")

        manipulator_instance = manipulator_class()
        result_meta = manipulator_instance.transform_annotation(meta, params)
        logger.info(
            "manipulator 적용 완료: name=%s, input_images=%d, output_images=%d",
            operator_name, meta.image_count, result_meta.image_count,
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

        merged_records: list[ImageRecord] = []
        image_id_counter = 1
        for meta in metas:
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
        output_meta의 image_records로부터 이미지 실체화 계획을 생성.

        각 이미지가 어느 소스에서 왔는지 file_name 기반으로 탐색한다.
        """
        plans: list[ImagePlan] = []

        for record in output_meta.image_records:
            src_uri: str | None = None
            for source_uri in source_storage_uris:
                candidate = f"{source_uri}/{self.images_dirname}/{record.file_name}"
                if self.storage.exists(candidate):
                    src_uri = candidate
                    break

            if src_uri is None:
                logger.warning(
                    "소스 이미지를 찾을 수 없음 (건너뜀): file_name=%s",
                    record.file_name,
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
            logger.info("COCO annotation 작성 완료: path=%s", output_path)
            return ["instances.json"]

        elif output_format == "YOLO":
            write_yolo_dir(output_meta, annotations_dir)
            label_files = sorted(
                f.name for f in annotations_dir.glob("*.txt")
            )
            logger.info("YOLO annotation 작성 완료: file_count=%d", len(label_files))
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
    images_dir = storage.get_images_dir(storage_uri)
    format_upper = annotation_format.upper()

    if format_upper == "COCO":
        json_path = annotations_dir / annotation_files[0]
        meta = parse_coco_json(json_path, dataset_id=dataset_id, storage_uri=storage_uri)
        return meta

    elif format_upper == "YOLO":
        yaml_path = None
        if annotation_meta_file:
            yaml_path = annotations_dir / annotation_meta_file

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
