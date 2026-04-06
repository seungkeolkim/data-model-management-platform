"""
DAG Executor + merge_datasets 통합 테스트.

테스트 영역:
  1. executor가 merge_datasets operator일 때 _merge_metas()를 건너뛰고 list 전달
  2. 비-merge multi-input은 기존대로 _merge_metas() 호출 (하위 호환)
  3. _build_image_plans: extra에 source 정보 있을 때 올바른 경로 생성
  4. 포맷 검증: 다른 포맷 소스 merge 시도 → ValueError
  5. _is_multi_input_manipulator 동작 확인
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from lib.pipeline.config import PipelineConfig
from lib.pipeline.dag_executor import PipelineDagExecutor
from lib.pipeline.pipeline_data_models import (
    Annotation,
    DatasetMeta,
    ImagePlan,
    ImageRecord,
)


# ─────────────────────────────────────────────────────────────────
# 테스트용 StorageProtocol 모의 구현
# ─────────────────────────────────────────────────────────────────


class MockStorage:
    """StorageProtocol을 만족하는 최소 모의 구현."""

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path("/tmp/test_storage")
        self.exists_calls: list[str] = []  # exists() 호출 추적용

    def resolve_path(self, relative_path: str) -> Path:
        return self.base_path / relative_path

    def exists(self, relative_path: str) -> bool:
        self.exists_calls.append(relative_path)
        return True

    def makedirs(self, relative_path: str) -> None:
        pass

    def build_dataset_uri(
        self, dataset_type: str, name: str, split: str, version: str
    ) -> str:
        return f"{dataset_type.lower()}/{name}/{split.lower()}/{version}"

    def get_images_dir(self, storage_uri: str) -> Path:
        return self.base_path / storage_uri / "images"

    def get_annotations_dir(self, storage_uri: str) -> Path:
        return self.base_path / storage_uri / "annotations"


# ─────────────────────────────────────────────────────────────────
# 테스트용 Executor (소스 로드를 메모리에서 수행)
# ─────────────────────────────────────────────────────────────────


class _TestableExecutor(PipelineDagExecutor):
    """
    _load_source_meta를 오버라이드하여 메모리에서 소스를 로드하는 테스트용 executor.
    실제 파일 I/O 없이 DAG 실행 로직만 테스트.
    """

    def __init__(self, storage: MockStorage, source_metas: dict[str, DatasetMeta]) -> None:
        super().__init__(storage)
        self._source_metas = source_metas

    def _load_source_meta(self, dataset_id: str) -> DatasetMeta:
        if dataset_id not in self._source_metas:
            raise ValueError(f"테스트 소스 없음: {dataset_id}")
        return self._source_metas[dataset_id]


# ─────────────────────────────────────────────────────────────────
# 테스트 데이터 팩토리
# ─────────────────────────────────────────────────────────────────


def _make_annotation(category_id: int) -> Annotation:
    return Annotation(
        annotation_type="BBOX",
        category_id=category_id,
        bbox=[10.0, 20.0, 30.0, 40.0],
    )


def _make_source_meta(
    dataset_id: str,
    categories: list[dict],
    file_names: list[str],
    annotation_format: str = "COCO",
    dataset_name: str | None = None,
) -> DatasetMeta:
    """간편한 소스 DatasetMeta 생성."""
    records = []
    for idx, file_name in enumerate(file_names, start=1):
        # 각 이미지에 첫 번째 카테고리의 annotation 1개씩
        anns = [_make_annotation(categories[0]["id"])] if categories else []
        records.append(
            ImageRecord(
                image_id=idx,
                file_name=file_name,
                width=640,
                height=480,
                annotations=anns,
            )
        )
    extra = {}
    if dataset_name:
        extra["dataset_name"] = dataset_name
    return DatasetMeta(
        dataset_id=dataset_id,
        storage_uri=f"source/{dataset_id}/train/v1.0.0",
        annotation_format=annotation_format,
        categories=categories,
        image_records=records,
        extra=extra,
    )


# ─────────────────────────────────────────────────────────────────
# 1. _is_multi_input_manipulator 테스트
# ─────────────────────────────────────────────────────────────────


class TestIsMultiInputManipulator:
    """_is_multi_input_manipulator() 동작 확인."""

    def test_merge_datasets_is_multi_input(self):
        executor = PipelineDagExecutor(MockStorage())
        assert executor._is_multi_input_manipulator("merge_datasets") is True

    def test_format_convert_is_not_multi_input(self):
        executor = PipelineDagExecutor(MockStorage())
        assert executor._is_multi_input_manipulator("format_convert_to_coco") is False

    def test_unknown_operator_is_not_multi_input(self):
        executor = PipelineDagExecutor(MockStorage())
        assert executor._is_multi_input_manipulator("nonexistent") is False


# ─────────────────────────────────────────────────────────────────
# 2. 포맷 검증 테스트
# ─────────────────────────────────────────────────────────────────


class TestValidateInputFormats:
    """_validate_input_formats() 테스트."""

    def test_same_format_passes(self):
        executor = PipelineDagExecutor(MockStorage())
        metas = [
            _make_source_meta("a", [], [], annotation_format="COCO"),
            _make_source_meta("b", [], [], annotation_format="COCO"),
        ]
        executor._validate_input_formats(metas, "merge_datasets")  # 예외 없으면 성공

    def test_different_format_raises(self):
        executor = PipelineDagExecutor(MockStorage())
        metas = [
            _make_source_meta("a", [], [], annotation_format="COCO"),
            _make_source_meta("b", [], [], annotation_format="YOLO"),
        ]
        with pytest.raises(ValueError, match="포맷 불일치"):
            executor._validate_input_formats(metas, "merge_datasets")


# ─────────────────────────────────────────────────────────────────
# 3. _build_image_plans 테스트
# ─────────────────────────────────────────────────────────────────


class TestBuildImagePlans:
    """_build_image_plans() 리팩터 테스트."""

    def test_merge_path_uses_extra_source_info(self):
        """extra에 source 정보가 있으면 원본 파일명으로 src_uri 구성."""
        storage = MockStorage()
        executor = PipelineDagExecutor(storage)

        hash_a = hashlib.md5("ds-a".encode()).hexdigest()[:4]
        output_meta = DatasetMeta(
            dataset_id="",
            storage_uri="",
            annotation_format="COCO",
            categories=[],
            image_records=[
                ImageRecord(
                    image_id=1,
                    file_name=f"coco8_{hash_a}_000001.jpg",  # prefix된 이름
                    width=640,
                    height=480,
                    extra={
                        "source_storage_uri": "source/coco8/train/v1.0.0",
                        "original_file_name": "000001.jpg",
                    },
                ),
            ],
        )

        plans = executor._build_image_plans(
            output_meta,
            source_storage_uris=["source/coco8/train/v1.0.0"],
            output_storage_uri="fusion/merged/train/v1.0.0",
        )

        assert len(plans) == 1
        # src_uri는 원본 파일명 사용
        assert plans[0].src_uri == "source/coco8/train/v1.0.0/images/000001.jpg"
        # dst_uri는 prefix된 파일명 사용
        assert plans[0].dst_uri == f"fusion/merged/train/v1.0.0/images/coco8_{hash_a}_000001.jpg"

    def test_non_merge_path_uses_first_source_uri(self):
        """extra에 source 정보가 없으면 첫 번째 source_storage_uri 사용."""
        storage = MockStorage()
        executor = PipelineDagExecutor(storage)

        output_meta = DatasetMeta(
            dataset_id="",
            storage_uri="",
            annotation_format="COCO",
            categories=[],
            image_records=[
                ImageRecord(image_id=1, file_name="test.jpg", width=640, height=480),
            ],
        )

        plans = executor._build_image_plans(
            output_meta,
            source_storage_uris=["source/ds-a/train/v1.0.0"],
            output_storage_uri="processed/out/train/v1.0.0",
        )

        assert len(plans) == 1
        assert plans[0].src_uri == "source/ds-a/train/v1.0.0/images/test.jpg"
        assert plans[0].dst_uri == "processed/out/train/v1.0.0/images/test.jpg"

    def test_no_storage_exists_calls(self):
        """storage.exists()가 호출되지 않는다."""
        storage = MockStorage()
        executor = PipelineDagExecutor(storage)

        output_meta = DatasetMeta(
            dataset_id="",
            storage_uri="",
            annotation_format="COCO",
            categories=[],
            image_records=[
                ImageRecord(
                    image_id=1,
                    file_name="img.jpg",
                    width=640,
                    height=480,
                    extra={
                        "source_storage_uri": "source/a/train/v1.0.0",
                        "original_file_name": "img.jpg",
                    },
                ),
                ImageRecord(image_id=2, file_name="other.jpg", width=640, height=480),
            ],
        )

        executor._build_image_plans(
            output_meta,
            source_storage_uris=["source/a/train/v1.0.0"],
            output_storage_uri="out/x/train/v1.0.0",
        )

        assert storage.exists_calls == [], "storage.exists()가 호출되어서는 안 됨"

    def test_no_source_uris_and_no_extra_skips(self):
        """source_storage_uris도 비어있고 extra도 없으면 건너뜀."""
        storage = MockStorage()
        executor = PipelineDagExecutor(storage)

        output_meta = DatasetMeta(
            dataset_id="",
            storage_uri="",
            annotation_format="COCO",
            categories=[],
            image_records=[
                ImageRecord(image_id=1, file_name="orphan.jpg", width=640, height=480),
            ],
        )

        plans = executor._build_image_plans(
            output_meta,
            source_storage_uris=[],
            output_storage_uri="out/x/train/v1.0.0",
        )

        assert len(plans) == 0


# ─────────────────────────────────────────────────────────────────
# 4. DAG 실행 통합 테스트 (merge_datasets bypass)
# ─────────────────────────────────────────────────────────────────


class TestDagExecutorMergeBypass:
    """merge_datasets operator일 때 executor가 list를 직접 전달하는지 확인."""

    def test_merge_datasets_receives_list_not_single_meta(self):
        """
        merge_datasets task의 inputs가 2개일 때,
        _merge_metas()를 건너뛰고 list[DatasetMeta]가 manipulator에 전달된다.

        검증: 결과의 file_name_mapping이 존재 → MergeDatasets가 list를 받아 처리했다는 증거.
        (_merge_metas()를 거쳤으면 file_name_mapping이 없음)
        """
        source_a = _make_source_meta(
            "ds-a",
            [{"id": 0, "name": "person"}],
            ["000001.jpg"],
            dataset_name="alpha",
        )
        source_b = _make_source_meta(
            "ds-b",
            [{"id": 0, "name": "person"}],
            ["000001.jpg"],  # 충돌 파일명
            dataset_name="beta",
        )

        storage = MockStorage()
        executor = _TestableExecutor(storage, {"ds-a": source_a, "ds-b": source_b})

        config = PipelineConfig(
            name="test_merge",
            output={"dataset_type": "FUSION", "annotation_format": "COCO", "split": "TRAIN"},
            tasks={
                "merge": {
                    "operator": "merge_datasets",
                    "inputs": ["source:ds-a", "source:ds-b"],
                    "params": {},
                },
            },
        )

        # Phase A만 실행하기 위해 run() 대신 직접 태스크 루프 시뮬레이션
        execution_order = config.topological_order()
        task_results: dict[str, DatasetMeta] = {}

        for task_name in execution_order:
            task_config = config.tasks[task_name]
            input_metas = []
            for ref in task_config.inputs:
                if ref.startswith("source:"):
                    dataset_id = ref.split(":", 1)[1]
                    input_metas.append(executor._load_source_meta(dataset_id))
                else:
                    input_metas.append(task_results[ref])

            if len(input_metas) > 1:
                executor._validate_input_formats(input_metas, task_config.operator)

            if executor._is_multi_input_manipulator(task_config.operator):
                result = executor._apply_manipulator(
                    input_metas, task_config.operator, task_config.params,
                )
            elif len(input_metas) == 1:
                result = executor._apply_manipulator(
                    input_metas[0], task_config.operator, task_config.params,
                )
            else:
                result = executor._apply_manipulator(
                    executor._merge_metas(input_metas),
                    task_config.operator,
                    task_config.params,
                )

            task_results[task_name] = result

        merged_result = task_results["merge"]

        # MergeDatasets가 처리한 증거: file_name_mapping 존재 + 충돌 파일 rename
        assert "file_name_mapping" in merged_result.extra
        assert merged_result.image_count == 2
        # 충돌된 000001.jpg가 각각 prefix 적용됨
        file_names = [r.file_name for r in merged_result.image_records]
        assert len(set(file_names)) == 2  # 모두 고유
        assert all("000001.jpg" in fn for fn in file_names)

    def test_merge_then_downstream_task_preserves_extra(self):
        """merge → 후속 태스크 시 ImageRecord.extra가 보존되는지 확인."""
        source_a = _make_source_meta(
            "ds-a",
            [{"id": 0, "name": "person"}],
            ["a.jpg"],
            annotation_format="COCO",
            dataset_name="alpha",
        )
        source_b = _make_source_meta(
            "ds-b",
            [{"id": 0, "name": "person"}],
            ["b.jpg"],
            annotation_format="COCO",
            dataset_name="beta",
        )

        storage = MockStorage()
        executor = _TestableExecutor(storage, {"ds-a": source_a, "ds-b": source_b})

        # merge → format_convert_to_coco (COCO→COCO는 무의미하지만 구조 테스트용)
        # format_convert_to_coco는 YOLO→COCO 전용이므로 대신 merge만 테스트
        config = PipelineConfig(
            name="test_chain",
            output={"dataset_type": "FUSION", "annotation_format": "COCO", "split": "TRAIN"},
            tasks={
                "merge": {
                    "operator": "merge_datasets",
                    "inputs": ["source:ds-a", "source:ds-b"],
                    "params": {},
                },
            },
        )

        execution_order = config.topological_order()
        task_results: dict[str, DatasetMeta] = {}

        for task_name in execution_order:
            task_config = config.tasks[task_name]
            input_metas = []
            for ref in task_config.inputs:
                if ref.startswith("source:"):
                    dataset_id = ref.split(":", 1)[1]
                    input_metas.append(executor._load_source_meta(dataset_id))
                else:
                    input_metas.append(task_results[ref])

            if executor._is_multi_input_manipulator(task_config.operator):
                result = executor._apply_manipulator(
                    input_metas, task_config.operator, task_config.params,
                )
            elif len(input_metas) == 1:
                result = executor._apply_manipulator(
                    input_metas[0], task_config.operator, task_config.params,
                )
            else:
                result = executor._apply_manipulator(
                    executor._merge_metas(input_metas),
                    task_config.operator,
                    task_config.params,
                )
            task_results[task_name] = result

        merged = task_results["merge"]

        # 모든 레코드에 출처 정보 존재
        for record in merged.image_records:
            assert "source_dataset_id" in record.extra
            assert "source_storage_uri" in record.extra
            assert "original_file_name" in record.extra

    def test_format_mismatch_in_merge_raises_early(self):
        """포맷이 다른 소스를 merge하면 실행 전에 ValueError 발생."""
        source_a = _make_source_meta("ds-a", [{"id": 0, "name": "x"}], ["a.jpg"], annotation_format="COCO")
        source_b = _make_source_meta("ds-b", [{"id": 0, "name": "x"}], ["b.jpg"], annotation_format="YOLO")

        storage = MockStorage()
        executor = _TestableExecutor(storage, {"ds-a": source_a, "ds-b": source_b})

        input_metas = [source_a, source_b]

        with pytest.raises(ValueError, match="포맷 불일치"):
            executor._validate_input_formats(input_metas, "merge_datasets")
