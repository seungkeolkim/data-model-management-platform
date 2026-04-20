"""
파이프라인 DAG 실행 엔진.

PipelineConfig의 tasks를 topological sort하여 순서대로 실행한다.
각 태스크는 입력(source 데이터셋 또는 이전 태스크 출력)을 받아
manipulator를 적용하고 DatasetMeta를 출력한다.

통일포맷:
  - 내부에서 annotation_format 구분 없이 category_name(문자열)으로 처리.
  - 디스크 포맷(COCO/YOLO)은 로드 시 파라미터로 전달, 저장 시 config.output.annotation_format으로 결정.

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
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from lib.manipulators import MANIPULATOR_REGISTRY
from lib.pipeline.config import PipelineConfig, TaskConfig
from lib.pipeline.image_materializer import ImageMaterializer
from lib.pipeline.io.coco_io import parse_coco_json, write_coco_json
from lib.pipeline.io.manifest_io import parse_manifest_dir, write_manifest_dir
from lib.pipeline.io.yolo_io import parse_yolo_dir, write_yolo_dir
from lib.pipeline.pipeline_data_models import (
    Annotation, DatasetMeta, DatasetPlan, ImageManipulationSpec, ImagePlan, ImageRecord,
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

    # 태스크 진행 콜백 시그니처:
    #   (task_name, status, detail_dict) -> None
    #   status: "PENDING" | "RUNNING" | "DONE" | "FAILED"
    #   detail_dict: {"operator": str, "started_at": str, "finished_at": str, "input_images": int, "output_images": int, ...}
    TaskProgressCallback = Callable[[str, str, dict[str, Any]], None]

    def __init__(
        self,
        storage: StorageProtocol,
        images_dirname: str = "images",
        on_task_progress: TaskProgressCallback | None = None,
    ) -> None:
        self.storage = storage
        self.images_dirname = images_dirname
        self._on_task_progress = on_task_progress

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
        # ── 파일 로그 수집기 설정 ──
        log_buffer_handler = _ProcessingLogBufferHandler()
        log_buffer_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
        )
        pipeline_root_logger = logging.getLogger("lib")
        pipeline_root_logger.addHandler(log_buffer_handler)

        try:
            return self._run_pipeline(
                config, target_version, log_buffer_handler, pipeline_root_logger,
            )
        finally:
            pipeline_root_logger.removeHandler(log_buffer_handler)

    def _run_pipeline(
        self,
        config: PipelineConfig,
        target_version: str,
        log_buffer_handler: '_ProcessingLogBufferHandler',
        pipeline_root_logger: logging.Logger,
    ) -> 'PipelineResult':
        """파이프라인 실제 실행 로직. run()에서 호출된다."""
        logger.info(
            "파이프라인 실행 시작: name=%s, tasks=%d, passthrough=%s",
            config.name, len(config.tasks), config.is_passthrough,
        )

        # ── Passthrough 모드: tasks 가 비어있으면 소스를 그대로 output 으로 복사 ──
        if config.is_passthrough:
            return self._run_passthrough(
                config, target_version, log_buffer_handler,
            )

        execution_order = config.topological_order()
        terminal_task_name = config.get_terminal_task_name()

        logger.info("실행 순서: %s", " → ".join(execution_order))

        # ── Phase A: DAG 태스크 순차 실행 (annotation 처리) ──
        # 태스크명 → 해당 태스크의 출력 DatasetMeta
        task_results: dict[str, DatasetMeta] = {}
        # 태스크별 source storage_uri 수집 (이미지 실체화용)
        all_source_storage_uris: list[str] = []

        # 태스크 진행 콜백: 전체 태스크를 PENDING으로 초기화
        if self._on_task_progress:
            for task_name in execution_order:
                task_config = config.tasks[task_name]
                self._on_task_progress(task_name, "PENDING", {
                    "operator": task_config.operator,
                })

        for task_name in execution_order:
            task_config = config.tasks[task_name]
            task_started_at = datetime.now(timezone.utc).isoformat()

            logger.info(
                "태스크 실행: %s (operator=%s, inputs=%s)",
                task_name, task_config.operator, task_config.inputs,
            )

            # 태스크 진행 콜백: RUNNING
            if self._on_task_progress:
                self._on_task_progress(task_name, "RUNNING", {
                    "operator": task_config.operator,
                    "started_at": task_started_at,
                })

            # 입력 DatasetMeta 수집
            input_metas: list[DatasetMeta] = []

            for ref in task_config.inputs:
                if ref.startswith("source:"):
                    # 소스 데이터셋 로드
                    dataset_id = ref.split(":", 1)[1]
                    source_meta = self._load_source_meta(dataset_id)
                    all_source_storage_uris.append(source_meta.storage_uri)
                    logger.info(
                        "소스 로드 완료: dataset_id=%s, images=%d, categories=%d",
                        dataset_id, source_meta.image_count,
                        len(source_meta.categories),
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

            # 입력 이미지 수 집계 (진행 추적용)
            input_image_count = sum(m.image_count for m in input_metas)

            # multi-input manipulator(예: det_merge_datasets)는 list를 직접 받고,
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
            # DAG 분기 시 동일 소스의 중간 결과를 구분하기 위해
            # 각 태스크 출력에 고유 dataset_id를 부여한다.
            # 이것이 없으면 merge가 같은 dataset_id를 가진 레코드들의
            # 파일명 충돌을 감지하지 못해 이미지가 덮어쓰기된다.
            result_meta.dataset_id = f"__task__{task_name}__{uuid.uuid4().hex[:8]}"
            task_results[task_name] = result_meta

            task_finished_at = datetime.now(timezone.utc).isoformat()
            logger.info(
                "태스크 완료: %s → images=%d, categories=%d",
                task_name, result_meta.image_count, len(result_meta.categories),
            )

            # 태스크 진행 콜백: DONE
            if self._on_task_progress:
                self._on_task_progress(task_name, "DONE", {
                    "operator": task_config.operator,
                    "started_at": task_started_at,
                    "finished_at": task_finished_at,
                    "input_images": input_image_count,
                    "output_images": result_meta.image_count,
                })

        # 최종 태스크의 출력이 파이프라인의 최종 결과
        output_meta = task_results[terminal_task_name]

        # 출력 포맷은 config에서 결정 (통일포맷이므로 내부 모델에 포맷 정보 없음)
        output_format = config.output.annotation_format.upper()

        logger.info(
            "Phase A 완료 (annotation 처리): images=%d, categories=%d, output_format=%s",
            output_meta.image_count, len(output_meta.categories), output_format,
        )

        # ── Phase B: 공통 실체화 경로 ──
        return self._materialize_and_write(
            config=config,
            target_version=target_version,
            output_meta=output_meta,
            all_source_storage_uris=all_source_storage_uris,
            output_format=output_format,
            log_buffer_handler=log_buffer_handler,
        )

    # -------------------------------------------------------------------------
    # Passthrough (Load → Save 직결)
    # -------------------------------------------------------------------------

    def _run_passthrough(
        self,
        config: PipelineConfig,
        target_version: str,
        log_buffer_handler: '_ProcessingLogBufferHandler',
    ) -> 'PipelineResult':
        """
        Tasks 가 없는 파이프라인 — 소스 메타를 그대로 output 으로 복사한다.

        annotation 변환 없음. 이미지는 기존 Phase B 경로로 lazy-copy 된다.
        """
        source_dataset_id = config.passthrough_source_dataset_id
        assert source_dataset_id is not None, "is_passthrough 체크에서 보장되어야 함"

        logger.info("Passthrough 모드: source=%s", source_dataset_id)

        # Load 단계 진행 콜백 (단일 synthetic task)
        passthrough_task_name = "__passthrough_load__"
        load_started_at = datetime.now(timezone.utc).isoformat()
        if self._on_task_progress:
            self._on_task_progress(passthrough_task_name, "RUNNING", {
                "operator": "passthrough_load",
                "started_at": load_started_at,
            })

        source_meta = self._load_source_meta(source_dataset_id)
        all_source_storage_uris = [source_meta.storage_uri]

        # 소스를 output 으로 그대로 사용. Phase B 에서 storage_uri 를 덮어쓴다.
        output_meta = source_meta

        if self._on_task_progress:
            self._on_task_progress(passthrough_task_name, "DONE", {
                "operator": "passthrough_load",
                "started_at": load_started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "input_images": output_meta.image_count,
                "output_images": output_meta.image_count,
            })

        output_format = config.output.annotation_format.upper()

        logger.info(
            "Phase A 완료 (passthrough): images=%d, task_kind=%s, output_format=%s",
            output_meta.image_count, output_meta.task_kind, output_format,
        )

        # ── Phase B: 공통 실체화 경로를 그대로 태운다 ──
        return self._materialize_and_write(
            config=config,
            target_version=target_version,
            output_meta=output_meta,
            all_source_storage_uris=all_source_storage_uris,
            output_format=output_format,
            log_buffer_handler=log_buffer_handler,
        )

    def _materialize_and_write(
        self,
        config: PipelineConfig,
        target_version: str,
        output_meta: DatasetMeta,
        all_source_storage_uris: list[str],
        output_format: str,
        log_buffer_handler: '_ProcessingLogBufferHandler',
    ) -> 'PipelineResult':
        """
        Phase B 공통 경로: 출력 경로 해석 → 이미지 실체화 → annotation 작성 → processing.log.

        _run_pipeline 과 _run_passthrough 가 공유한다.
        (원래 _run_pipeline 안에 인라인되어 있었으나 passthrough 도 같은 경로가 필요해 분리.)
        """
        image_materialize_started_at = datetime.now(timezone.utc).isoformat()
        if self._on_task_progress:
            self._on_task_progress("__image_materialize__", "RUNNING", {
                "operator": "image_materialize",
                "started_at": image_materialize_started_at,
                "total_images": output_meta.image_count,
            })

        output_dataset_type = config.output.dataset_type.upper()
        output_split = config.output.split.upper()

        output_storage_uri = self.storage.build_dataset_uri(
            dataset_type=output_dataset_type,
            name=config.name,
            split=output_split,
            version=target_version,
        )
        output_meta.storage_uri = output_storage_uri

        self.storage.makedirs(output_storage_uri)

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

        annotation_filenames = self._write_annotations(
            output_meta, output_storage_uri, output_format,
        )

        annotation_meta_filename: str | None = None
        if output_format == "YOLO":
            output_root_dir = self.storage.resolve_path(output_storage_uri)
            from lib.pipeline.io.yolo_io import _write_yolo_data_yaml
            sorted_category_names = sorted(output_meta.categories)
            _write_yolo_data_yaml(sorted_category_names, output_root_dir)
            annotation_meta_filename = "data.yaml"
            logger.info("YOLO data.yaml 생성 완료 (데이터셋 루트)")
        elif output_format == "CLS_MANIFEST":
            annotation_meta_filename = "head_schema.json"

        if self._on_task_progress:
            self._on_task_progress("__image_materialize__", "DONE", {
                "operator": "image_materialize",
                "started_at": image_materialize_started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "total_images": output_meta.image_count,
                "materialized": materialize_result.materialized_count,
                "skipped": materialize_result.skipped_count,
            })

        logger.info(
            "파이프라인 실행 완료: output_uri=%s, images=%d, skipped=%d, annotations=%d",
            output_storage_uri, materialize_result.materialized_count,
            materialize_result.skipped_count, len(annotation_filenames),
        )

        self._write_processing_log(
            output_storage_uri=output_storage_uri,
            config=config,
            log_lines=log_buffer_handler.get_log_lines(),
            materialize_result=materialize_result,
            annotation_filenames=annotation_filenames,
        )

        return PipelineResult(
            output_meta=output_meta,
            output_storage_uri=output_storage_uri,
            output_dataset_type=output_dataset_type,
            output_split=output_split,
            output_format=output_format,
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

        # 로깅
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
        """
        manipulator_class = MANIPULATOR_REGISTRY.get(operator_name)
        if manipulator_class is None:
            return False
        return getattr(manipulator_class, "accepts_multi_input", False)

    def _merge_metas(self, metas: list[DatasetMeta]) -> DatasetMeta:
        """
        다중 소스 DatasetMeta를 단순 병합한다 (통일포맷).

        categories는 name 기반 union (등장 순서 보존).
        annotation의 category_name은 그대로 유지 — 리매핑 불필요.
        image_id만 순차 재번호.
        """
        if not metas:
            raise ValueError("병합할 DatasetMeta가 없습니다.")

        # 카테고리 통합: name union (등장 순서 보존)
        merged_categories: list[str] = list(
            dict.fromkeys(name for meta in metas for name in meta.categories)
        )

        merged_records: list[ImageRecord] = []
        image_id_counter = 1
        for meta in metas:
            for record in meta.image_records:
                new_record = ImageRecord(
                    image_id=image_id_counter,
                    file_name=record.file_name,
                    width=record.width,
                    height=record.height,
                    annotations=list(record.annotations),
                    extra=record.extra,
                )
                merged_records.append(new_record)
                image_id_counter += 1

        return DatasetMeta(
            dataset_id="",
            storage_uri="",
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

        Detection 경로:
          - record.file_name 은 파일명만 (예: "000123.jpg"). images_dirname 을 덧붙여 경로 구성.
          - merge 경로면 record.extra.source_storage_uri + original_file_name 으로 원본 위치 지정.

        Classification 경로:
          - record.file_name 은 "images/{basename}" 상대경로 (manifest_io 규약).
          - merge 에서 파일명 충돌이 rename 된 경우 record.file_name 은
            "images/{display}_{md5_4}_{basename}" 형태가 된다. 소스 스토리지에는
            이 renamed 파일이 존재하지 않으므로, src 경로는 반드시
            record.extra.original_file_name (rename 이전의 원본 경로) 로 구성한다.
          - images_dirname 을 경로에 중복 부착하면 "images/images/..." 로 깨지므로
            detection 과 달리 분기 처리한다.
        """
        plans: list[ImagePlan] = []
        is_classification = output_meta.task_kind == "CLASSIFICATION"

        for record in output_meta.image_records:
            source_uri_override = record.extra.get("source_storage_uri")
            original_file_name = record.extra.get("original_file_name")

            if is_classification:
                # dst 는 merge rename 이 반영된 최종 이름.
                dst_uri = f"{output_storage_uri}/{record.file_name}"
                # src 는 rename 이전의 원본 경로여야 실제 파일을 찾을 수 있다.
                if source_uri_override and original_file_name:
                    src_uri = f"{source_uri_override}/{original_file_name}"
                elif source_storage_uris:
                    # 비-merge 경로: record.file_name 자체가 원본 경로와 동일.
                    src_uri = f"{source_storage_uris[0]}/{record.file_name}"
                else:
                    logger.warning(
                        "소스 경로를 결정할 수 없음 (건너뜀): file_name=%s",
                        record.file_name,
                    )
                    continue
            else:
                if source_uri_override and original_file_name:
                    src_uri = f"{source_uri_override}/{self.images_dirname}/{original_file_name}"
                elif source_storage_uris:
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

            # record.extra에 누적된 이미지 변환 명세 추출
            raw_specs = record.extra.pop("image_manipulation_specs", [])
            specs = [
                ImageManipulationSpec(operation=s["operation"], params=s.get("params", {}))
                for s in raw_specs
            ]

            plans.append(ImagePlan(src_uri=src_uri, dst_uri=dst_uri, specs=specs))

        return plans

    def _write_annotations(
        self,
        output_meta: DatasetMeta,
        output_storage_uri: str,
        output_format: str,
    ) -> list[str]:
        """
        output_meta를 포맷에 맞는 annotation 파일로 작성한다.

        Args:
            output_meta: 통일포맷 DatasetMeta
            output_storage_uri: 출력 경로
            output_format: 출력 포맷 ("COCO" | "YOLO")

        Returns:
            작성된 annotation 파일명 리스트
        """
        annotations_dir = self.storage.get_annotations_dir(output_storage_uri)
        annotations_dir.mkdir(parents=True, exist_ok=True)

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

        elif output_format == "CLS_MANIFEST":
            # Classification 전용: manifest.jsonl + head_schema.json 은 데이터셋 루트에 둔다.
            # annotations_dir 은 detection 규약이므로 사용하지 않는다.
            dataset_root = self.storage.resolve_path(output_storage_uri)
            write_manifest_dir(output_meta, dataset_root)
            logger.info(
                "CLS_MANIFEST 작성 완료: manifest.jsonl + head_schema.json @ %s",
                dataset_root,
            )
            # DB annotation_files 필드는 manifest.jsonl 하나만 기록한다.
            return ["manifest.jsonl"]

        else:
            raise ValueError(f"지원하지 않는 출력 포맷: {output_format}")

    def _write_processing_log(
        self,
        output_storage_uri: str,
        config: PipelineConfig,
        log_lines: list[str],
        materialize_result: 'MaterializeResult',
        annotation_filenames: list[str],
    ) -> None:
        """
        파이프라인 실행 과정을 output 디렉토리에 processing.log로 기록한다.
        """
        from lib.pipeline.image_materializer import MaterializeResult  # noqa: F811

        output_dir = self.storage.resolve_path(output_storage_uri)
        log_path = output_dir / "processing.log"

        try:
            with open(log_path, "w", encoding="utf-8") as log_file:
                # ── 헤더: 파이프라인 설정 요약 ──
                log_file.write("=" * 72 + "\n")
                log_file.write(f"  파이프라인 실행 로그 — {config.name}\n")
                log_file.write(f"  실행 시각: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                log_file.write("=" * 72 + "\n\n")

                # 출력 설정
                log_file.write("[출력 설정]\n")
                log_file.write(f"  출력 경로       : {output_storage_uri}\n")
                log_file.write(f"  데이터셋 타입   : {config.output.dataset_type}\n")
                log_file.write(f"  Split           : {config.output.split}\n")
                log_file.write(f"  어노테이션 포맷 : {config.output.annotation_format}\n")
                log_file.write("\n")

                # DAG 태스크 목록
                log_file.write("[DAG 태스크]\n")
                task_order = config.topological_order()
                for task_name in task_order:
                    task_config = config.tasks[task_name]
                    inputs_str = ", ".join(task_config.inputs)
                    params_str = str(task_config.params) if task_config.params else "{}"
                    log_file.write(
                        f"  {task_name}\n"
                        f"    operator : {task_config.operator}\n"
                        f"    inputs   : [{inputs_str}]\n"
                        f"    params   : {params_str}\n"
                    )
                log_file.write("\n")

                # 결과 요약
                log_file.write("[실행 결과 요약]\n")
                log_file.write(f"  최종 이미지 수       : {materialize_result.materialized_count}\n")
                log_file.write(f"  스킵된 이미지 수     : {materialize_result.skipped_count}\n")
                log_file.write(f"  생성된 어노테이션    : {', '.join(annotation_filenames)}\n")

                if materialize_result.skipped_count > 0:
                    log_file.write(f"\n[스킵된 이미지 목록] (총 {materialize_result.skipped_count}건)\n")
                    for skipped_file in materialize_result.skipped_files:
                        log_file.write(f"  - {skipped_file}\n")

                # 상세 실행 로그
                log_file.write("\n" + "=" * 72 + "\n")
                log_file.write("  상세 실행 로그\n")
                log_file.write("=" * 72 + "\n\n")
                for line in log_lines:
                    log_file.write(line + "\n")

            logger.info("processing.log 작성 완료: %s", log_path)

        except OSError as write_error:
            logger.warning(
                "processing.log 작성 실패 (파이프라인 결과에는 영향 없음): %s",
                write_error,
            )


# ─── Pipeline 실행 결과 ───

class PipelineResult:
    """
    파이프라인 실행 결과를 담는 컨테이너.

    output_format: 출력 annotation 포맷 ("COCO" | "YOLO")
    """

    def __init__(
        self,
        output_meta: DatasetMeta,
        output_storage_uri: str,
        output_dataset_type: str,
        output_split: str,
        output_format: str,
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
        self.output_format = output_format
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
    skip_image_sizes: bool = False,
) -> DatasetMeta:
    """
    스토리지에 저장된 데이터셋의 annotation을 파싱하여 통일포맷 DatasetMeta로 반환.
    DB 없이 파일 기반으로 로드한다 (CLI 테스트용 + 파이프라인 실행용).

    annotation_format 파라미터는 디스크의 파일 포맷을 판별하기 위해 사용된다.
    반환되는 DatasetMeta에는 annotation_format 필드가 없다 (통일포맷).

    Args:
        storage: StorageProtocol 구현체
        storage_uri: 데이터셋 상대경로 (예: "raw/coco8/train/v1.0.0")
        annotation_format: 디스크 포맷 (COCO | YOLO) — 파서 선택용
        annotation_files: 어노테이션 파일명 리스트
        annotation_meta_file: 메타 파일명 (예: data.yaml)
        dataset_id: DatasetMeta.dataset_id

    Returns:
        파싱된 DatasetMeta (통일포맷)
    """
    annotations_dir = storage.get_annotations_dir(storage_uri)
    images_dir = storage.get_images_dir(storage_uri)
    format_upper = annotation_format.upper()

    if format_upper == "COCO":
        json_path = annotations_dir / annotation_files[0]
        meta = parse_coco_json(json_path, dataset_id=dataset_id, storage_uri=storage_uri)
        return meta

    elif format_upper == "CLS_MANIFEST":
        # Classification: manifest.jsonl + head_schema.json 은 데이터셋 루트에 있다.
        # annotation_files / annotation_meta_file 파라미터는 사용하지 않는다.
        dataset_root = storage.resolve_path(storage_uri)
        meta = parse_manifest_dir(
            dataset_root=dataset_root,
            dataset_id=dataset_id,
            storage_uri=storage_uri,
        )
        return meta

    elif format_upper == "YOLO":
        yaml_path = None
        if annotation_meta_file:
            dataset_root = storage.resolve_path(storage_uri)
            yaml_path = dataset_root / annotation_meta_file
            if not yaml_path.exists():
                yaml_path = None

        # YOLO txt에는 이미지 크기 정보가 없으므로 Pillow로 읽어야 한다.
        image_sizes: dict[str, tuple[int, int]] = {}
        if not skip_image_sizes and images_dir.exists():
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


# ─── 파이프라인 실행 로그 버퍼 핸들러 ───

class _ProcessingLogBufferHandler(logging.Handler):
    """
    파이프라인 실행 중 발생하는 로그를 메모리에 버퍼링하는 핸들러.
    """

    def __init__(self) -> None:
        super().__init__()
        self._log_lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            formatted_message = self.format(record)
            self._log_lines.append(formatted_message)
        except Exception:
            self.handleError(record)

    def get_log_lines(self) -> list[str]:
        return self._log_lines
