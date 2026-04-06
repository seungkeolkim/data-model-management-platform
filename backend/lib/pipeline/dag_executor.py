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

    def run(
        self,
        config: PipelineConfig,
        target_version: str = "v1.0.0",
    ) -> PipelineResult:
        """
        파이프라인 전체 실행.

        Args:
            config: DAG 기반 파이프라인 설정
            target_version: 출력 데이터셋 버전. 서비스 레이어에서 자동 생성된 값을 전달한다.

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

            # 다중 입력 포맷 일치 검증
            if len(input_metas) > 1:
                self._validate_input_formats(input_metas, task_config.operator)

            # multi-input manipulator(예: merge_datasets)는 list를 직접 받고,
            # 그 외 multi-input은 기존 _merge_metas()로 단건 병합 후 전달
            if self._is_multi_input_manipulator(task_config.operator):
                result_meta = self._apply_manipulator(
                    input_metas, task_config.operator, task_config.params,
                )
            elif len(input_metas) == 1:
                result_meta = self._apply_manipulator(
                    input_metas[0], task_config.operator, task_config.params,
                )
            else:
                working_meta = self._merge_metas(input_metas)
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
            version=target_version,
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
        materialize_result = image_materializer.materialize(dataset_plan)

        # 스킵된 이미지가 있으면 output_meta에서 해당 레코드 제거
        # (annotation에 존재하지만 실제 파일이 없는 이미지 → 최종 결과물에서 제외)
        if materialize_result.skipped_count > 0:
            skipped_file_set = set(materialize_result.skipped_files)
            original_count = len(output_meta.image_records)
            output_meta.image_records = [
                record for record in output_meta.image_records
                if record.file_name not in skipped_file_set
            ]
            logger.warning(
                "스킵된 이미지 제거: 원본 %d → 필터링 후 %d (제거 %d건)",
                original_count, len(output_meta.image_records),
                materialize_result.skipped_count,
            )

        # annotation 파일 작성 (스킵된 이미지가 제거된 output_meta 기반)
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
            "파이프라인 실행 완료: output_uri=%s, images=%d, skipped=%d, annotations=%d",
            output_storage_uri, materialize_result.materialized_count,
            materialize_result.skipped_count, len(annotation_filenames),
        )

        return PipelineResult(
            output_meta=output_meta,
            output_storage_uri=output_storage_uri,
            output_dataset_type=output_dataset_type,
            output_split=output_split,
            annotation_filenames=annotation_filenames,
            annotation_meta_filename=annotation_meta_filename,
            image_count=materialize_result.materialized_count,
            source_dataset_ids=config.get_all_source_dataset_ids(),
            skipped_image_count=materialize_result.skipped_count,
            skipped_image_files=materialize_result.skipped_files,
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
        meta: DatasetMeta | list[DatasetMeta],
        operator_name: str,
        params: dict[str, Any],
    ) -> DatasetMeta:
        """
        manipulator(operator)를 DatasetMeta에 적용한다.

        multi-input manipulator(accepts_multi_input=True)는 list[DatasetMeta]를 받고,
        일반 manipulator는 단건 DatasetMeta를 받는다.
        """
        manipulator_class = MANIPULATOR_REGISTRY.get(operator_name)
        if manipulator_class is None:
            raise ValueError(f"등록되지 않은 manipulator: {operator_name}")

        manipulator_instance = manipulator_class()
        result_meta = manipulator_instance.transform_annotation(meta, params)

        # 로깅: list 입력일 경우 총 이미지 수 합산
        if isinstance(meta, list):
            input_image_count = sum(m.image_count for m in meta)
        else:
            input_image_count = meta.image_count
        logger.info(
            "manipulator 적용 완료: name=%s, input_images=%d, output_images=%d",
            operator_name, input_image_count, result_meta.image_count,
        )
        return result_meta

    def _is_multi_input_manipulator(self, operator_name: str) -> bool:
        """
        해당 operator가 list[DatasetMeta]를 직접 받는 multi-input manipulator인지 확인한다.
        클래스에 accepts_multi_input = True 속성이 있으면 True.
        """
        manipulator_class = MANIPULATOR_REGISTRY.get(operator_name)
        if manipulator_class is None:
            return False
        return getattr(manipulator_class, "accepts_multi_input", False)

    def _validate_input_formats(
        self,
        input_metas: list[DatasetMeta],
        operator_name: str,
    ) -> None:
        """
        multi-input 태스크의 모든 입력이 동일 annotation_format인지 검증한다.

        annotation_format이 불일치하면 DAG 실행 전에 빠르게 실패시킨다.
        (DB 관점의 SQL parser처럼 실행 전 type mismatch를 감지)
        """
        formats = {meta.annotation_format.upper() for meta in input_metas}
        if len(formats) > 1:
            detail = [
                (meta.dataset_id, meta.annotation_format) for meta in input_metas
            ]
            raise ValueError(
                f"포맷 불일치: operator='{operator_name}'의 입력들이 "
                f"서로 다른 annotation_format을 가지고 있습니다: {detail}"
            )

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

        소스 이미지 경로 결정 방식:
          1. record.extra에 source_storage_uri + original_file_name이 있으면 (merge 경로)
             → 원본 파일명으로 소스 경로를 직접 구성
          2. 없으면 (단일 소스 경로)
             → source_storage_uris의 첫 번째 URI를 사용

        storage.exists() 호출 없음 — 등록된 데이터는 존재한다고 가정.
        파일이 실제로 없으면 ImageMaterializer에서 복사 시점에 에러 발생.
        """
        plans: list[ImagePlan] = []

        for record in output_meta.image_records:
            source_uri = record.extra.get("source_storage_uri")
            original_file_name = record.extra.get("original_file_name")

            if source_uri and original_file_name:
                # merge 경로: 원본 파일명으로 소스를 찾고, 현재 file_name(prefix 적용된)으로 출력
                src_uri = f"{source_uri}/{self.images_dirname}/{original_file_name}"
            elif source_storage_uris:
                # 비-merge 경로: 첫 번째 소스 URI 사용 (단일 소스 전제)
                src_uri = (
                    f"{source_storage_uris[0]}/{self.images_dirname}/{record.file_name}"
                )
            else:
                logger.warning(
                    "소스 경로를 결정할 수 없음 (건너뜀): file_name=%s",
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
    """
    파이프라인 실행 결과를 담는 컨테이너.

    skipped_image_count/skipped_image_files는 annotation에 존재하지만
    실제 소스 파일이 없어 건너뛴 이미지 정보를 담는다.
    """

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
        skipped_image_count: int = 0,
        skipped_image_files: list[str] | None = None,
    ) -> None:
        self.output_meta = output_meta
        self.output_storage_uri = output_storage_uri
        self.output_dataset_type = output_dataset_type
        self.output_split = output_split
        self.annotation_filenames = annotation_filenames
        self.annotation_meta_filename = annotation_meta_filename
        self.image_count = image_count
        self.source_dataset_ids = source_dataset_ids
        self.skipped_image_count = skipped_image_count
        self.skipped_image_files = skipped_image_files or []


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
