"""
PipelineConfig DAG 구조 단위 테스트.

검증 항목:
  - YAML 파싱 → PipelineConfig 변환
  - topological sort 순서
  - 순환 참조 감지
  - 존재하지 않는 태스크 참조 감지
  - 자기 참조 감지
  - 터미널 태스크(sink 노드) 식별
  - source dataset_id 수집
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from lib.pipeline.config import (
    OutputConfig,
    PipelineConfig,
    TaskConfig,
    load_pipeline_config_from_yaml,
)

# output이 테스트 관심사가 아닌 경우에 사용하는 기본 OutputConfig
_DEFAULT_OUTPUT = {"annotation_format": "COCO"}


# =============================================================================
# PipelineConfig 기본 생성
# =============================================================================

class TestPipelineConfigBasic:
    """PipelineConfig 기본 생성 및 필드 검증."""

    def test_single_task_pipeline(self):
        """단일 태스크 파이프라인 생성."""
        config = PipelineConfig(
            name="simple_convert",
            output=OutputConfig(dataset_type="SOURCE", annotation_format="COCO", split="TRAIN"),
            tasks={
                "convert": TaskConfig(
                    operator="det_format_convert_to_coco",
                    inputs=["source:abc-123"],
                    params={},
                ),
            },
        )
        assert config.name == "simple_convert"
        assert config.output.dataset_type == "SOURCE"
        assert config.output.split == "TRAIN"
        assert len(config.tasks) == 1

    def test_multi_task_pipeline(self):
        """다중 태스크 파이프라인 (체인)."""
        config = PipelineConfig(
            name="chain_pipeline",
            output={"annotation_format": "COCO"},
            tasks={
                "step_1": TaskConfig(
                    operator="det_format_convert_to_coco",
                    inputs=["source:aaa"],
                ),
                "step_2": TaskConfig(
                    operator="det_remap_class_name",
                    inputs=["step_1"],
                    params={"mapping": {"van": "car"}},
                ),
            },
        )
        assert len(config.tasks) == 2

    def test_output_defaults(self):
        """OutputConfig 기본값 확인 (annotation_format은 필수)."""
        config = PipelineConfig(
            name="default_output",
            output={"annotation_format": "COCO"},
            tasks={
                "t1": TaskConfig(operator="op", inputs=["source:x"]),
            },
        )
        assert config.output.dataset_type == "SOURCE"
        assert config.output.annotation_format == "COCO"
        assert config.output.split == "NONE"

    def test_output_without_annotation_format_rejected(self):
        """annotation_format 없이 OutputConfig 생성 → ValidationError."""
        with pytest.raises(Exception):
            PipelineConfig(
                name="no_format",
                tasks={
                    "t1": TaskConfig(operator="op", inputs=["source:x"]),
                },
            )

    def test_empty_tasks_rejected(self):
        """tasks가 비어있으면 ValidationError."""
        with pytest.raises(Exception):
            PipelineConfig(name="empty", tasks={})

    def test_task_without_inputs_rejected(self):
        """inputs가 비어있으면 ValidationError."""
        with pytest.raises(Exception):
            PipelineConfig(
                name="no_inputs",
                tasks={
                    "t1": TaskConfig(operator="op", inputs=[]),
                },
            )


# =============================================================================
# DAG 검증
# =============================================================================

class TestDagValidation:
    """DAG 구조 검증 (순환 참조, 잘못된 참조)."""

    def test_invalid_task_reference_rejected(self):
        """존재하지 않는 태스크를 참조하면 ValidationError."""
        with pytest.raises(ValueError, match="정의된 태스크 목록에 없습니다"):
            PipelineConfig(
                name="bad_ref",
                output=_DEFAULT_OUTPUT,
                tasks={
                    "t1": TaskConfig(operator="op", inputs=["source:x"]),
                    "t2": TaskConfig(operator="op", inputs=["nonexistent"]),
                },
            )

    def test_self_reference_rejected(self):
        """자기 자신을 참조하면 ValidationError."""
        with pytest.raises(ValueError, match="자기 자신을 input으로 참조"):
            PipelineConfig(
                name="self_ref",
                output=_DEFAULT_OUTPUT,
                tasks={
                    "t1": TaskConfig(operator="op", inputs=["t1"]),
                },
            )

    def test_cycle_detected(self):
        """순환 참조가 있으면 ValidationError."""
        with pytest.raises(ValueError, match="순환 참조"):
            PipelineConfig(
                name="cycle",
                output=_DEFAULT_OUTPUT,
                tasks={
                    "a": TaskConfig(operator="op", inputs=["source:x", "c"]),
                    "b": TaskConfig(operator="op", inputs=["a"]),
                    "c": TaskConfig(operator="op", inputs=["b"]),
                },
            )

    def test_diamond_dag_is_valid(self):
        """다이아몬드 DAG (A→B, A→C, B→D, C→D)는 유효."""
        config = PipelineConfig(
            name="diamond",
            output=_DEFAULT_OUTPUT,
            tasks={
                "a": TaskConfig(operator="op", inputs=["source:x"]),
                "b": TaskConfig(operator="op", inputs=["a"]),
                "c": TaskConfig(operator="op", inputs=["a"]),
                "d": TaskConfig(operator="op", inputs=["b", "c"]),
            },
        )
        assert len(config.tasks) == 4

    def test_source_reference_does_not_need_task(self):
        """'source:' 접두사는 태스크 이름이 아니므로 검증에서 무시."""
        config = PipelineConfig(
            name="source_only",
            output=_DEFAULT_OUTPUT,
            tasks={
                "t1": TaskConfig(operator="op", inputs=["source:dataset-1", "source:dataset-2"]),
            },
        )
        assert len(config.tasks) == 1


# =============================================================================
# Topological Sort
# =============================================================================

class TestTopologicalOrder:
    """topological_order() 검증."""

    def test_single_task(self):
        config = PipelineConfig(
            name="single",
            output=_DEFAULT_OUTPUT,
            tasks={
                "only": TaskConfig(operator="op", inputs=["source:x"]),
            },
        )
        assert config.topological_order() == ["only"]

    def test_linear_chain(self):
        """A → B → C 선형 체인."""
        config = PipelineConfig(
            name="chain",
            output=_DEFAULT_OUTPUT,
            tasks={
                "c": TaskConfig(operator="op", inputs=["b"]),
                "a": TaskConfig(operator="op", inputs=["source:x"]),
                "b": TaskConfig(operator="op", inputs=["a"]),
            },
        )
        order = config.topological_order()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_diamond_order(self):
        """다이아몬드 DAG에서 d는 반드시 마지막."""
        config = PipelineConfig(
            name="diamond",
            output=_DEFAULT_OUTPUT,
            tasks={
                "a": TaskConfig(operator="op", inputs=["source:x"]),
                "b": TaskConfig(operator="op", inputs=["a"]),
                "c": TaskConfig(operator="op", inputs=["a"]),
                "d": TaskConfig(operator="op", inputs=["b", "c"]),
            },
        )
        order = config.topological_order()
        assert order[0] == "a"
        assert order[-1] == "d"
        # b, c 순서는 알파벳순 (sorted 사용)
        assert set(order[1:3]) == {"b", "c"}

    def test_two_independent_sources(self):
        """독립적인 2개 소스 → merge."""
        config = PipelineConfig(
            name="two_sources",
            output=_DEFAULT_OUTPUT,
            tasks={
                "src_a": TaskConfig(operator="op", inputs=["source:a"]),
                "src_b": TaskConfig(operator="op", inputs=["source:b"]),
                "merge": TaskConfig(operator="op", inputs=["src_a", "src_b"]),
            },
        )
        order = config.topological_order()
        assert order[-1] == "merge"
        assert order.index("src_a") < order.index("merge")
        assert order.index("src_b") < order.index("merge")


# =============================================================================
# Terminal Task (Sink Node)
# =============================================================================

class TestTerminalTask:
    """get_terminal_task_name() 검증."""

    def test_single_task_is_terminal(self):
        config = PipelineConfig(
            name="single",
            output=_DEFAULT_OUTPUT,
            tasks={
                "only": TaskConfig(operator="op", inputs=["source:x"]),
            },
        )
        assert config.get_terminal_task_name() == "only"

    def test_chain_terminal(self):
        config = PipelineConfig(
            name="chain",
            output=_DEFAULT_OUTPUT,
            tasks={
                "a": TaskConfig(operator="op", inputs=["source:x"]),
                "b": TaskConfig(operator="op", inputs=["a"]),
                "c": TaskConfig(operator="op", inputs=["b"]),
            },
        )
        assert config.get_terminal_task_name() == "c"

    def test_multiple_terminals_rejected(self):
        """sink가 2개 이상이면 ValueError."""
        with pytest.raises(ValueError, match="최종 출력 태스크가 2개 이상"):
            config = PipelineConfig(
                name="multi_terminal",
                output=_DEFAULT_OUTPUT,
                tasks={
                    "a": TaskConfig(operator="op", inputs=["source:x"]),
                    "b": TaskConfig(operator="op", inputs=["source:y"]),
                },
            )
            config.get_terminal_task_name()


# =============================================================================
# Source Dataset ID 수집
# =============================================================================

class TestSourceDatasetIds:
    """get_all_source_dataset_ids() 검증."""

    def test_single_source(self):
        config = PipelineConfig(
            name="single_src",
            output=_DEFAULT_OUTPUT,
            tasks={
                "t1": TaskConfig(operator="op", inputs=["source:abc-123"]),
            },
        )
        assert config.get_all_source_dataset_ids() == ["abc-123"]

    def test_multiple_sources_deduped(self):
        """동일 source가 여러 태스크에서 참조되면 중복 제거."""
        config = PipelineConfig(
            name="dedup",
            output=_DEFAULT_OUTPUT,
            tasks={
                "t1": TaskConfig(operator="op", inputs=["source:aaa"]),
                "t2": TaskConfig(operator="op", inputs=["source:aaa", "source:bbb"]),
                "t3": TaskConfig(operator="op", inputs=["t1", "t2"]),
            },
        )
        ids = config.get_all_source_dataset_ids()
        assert ids == ["aaa", "bbb"]

    def test_no_sources(self):
        """source가 없는 경우 (이론적으로 불가능하지만)."""
        # 모든 태스크가 다른 태스크만 참조 — 이 경우 cycle이라 생성 불가
        # 최소 1개는 source가 있어야 DAG가 성립
        config = PipelineConfig(
            name="only_source",
            output=_DEFAULT_OUTPUT,
            tasks={
                "t1": TaskConfig(operator="op", inputs=["source:x"]),
            },
        )
        assert len(config.get_all_source_dataset_ids()) == 1


# =============================================================================
# TaskConfig 헬퍼 메서드
# =============================================================================

class TestTaskConfigHelpers:
    """TaskConfig의 get_source_dataset_ids, get_dependency_task_names."""

    def test_get_source_dataset_ids(self):
        task = TaskConfig(
            operator="op",
            inputs=["source:aaa", "source:bbb", "prev_task"],
        )
        assert task.get_source_dataset_ids() == ["aaa", "bbb"]

    def test_get_dependency_task_names(self):
        task = TaskConfig(
            operator="op",
            inputs=["source:aaa", "prev_task_1", "prev_task_2"],
        )
        assert task.get_dependency_task_names() == ["prev_task_1", "prev_task_2"]

    def test_source_only(self):
        task = TaskConfig(operator="op", inputs=["source:x"])
        assert task.get_source_dataset_ids() == ["x"]
        assert task.get_dependency_task_names() == []

    def test_task_only(self):
        task = TaskConfig(operator="op", inputs=["other_task"])
        assert task.get_source_dataset_ids() == []
        assert task.get_dependency_task_names() == ["other_task"]


# =============================================================================
# YAML 파싱
# =============================================================================

class TestYamlParsing:
    """load_pipeline_config_from_yaml() 검증."""

    def test_simple_yaml(self, tmp_path: Path):
        """단순 YAML 파싱."""
        yaml_content = textwrap.dedent("""\
            pipeline:
              name: "test_pipeline"
              description: "테스트 파이프라인"
              output:
                dataset_type: SOURCE
                annotation_format: COCO
                split: TRAIN
              tasks:
                convert:
                  operator: det_format_convert_to_coco
                  inputs: ["source:abc-123"]
                  params:
                    category_names:
                      - person
                      - car
        """)
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        config = load_pipeline_config_from_yaml(yaml_file)

        assert config.name == "test_pipeline"
        assert config.description == "테스트 파이프라인"
        assert config.output.dataset_type == "SOURCE"
        assert config.output.annotation_format == "COCO"
        assert config.output.split == "TRAIN"
        assert "convert" in config.tasks
        assert config.tasks["convert"].operator == "det_format_convert_to_coco"
        assert config.tasks["convert"].params["category_names"] == ["person", "car"]

    def test_multi_task_yaml(self, tmp_path: Path):
        """다중 태스크 YAML 파싱 + DAG 검증."""
        yaml_content = textwrap.dedent("""\
            pipeline:
              name: "multi_step"
              output:
                dataset_type: FUSION
                annotation_format: COCO
                split: TRAIN
              tasks:
                prep_a:
                  operator: det_format_convert_to_coco
                  inputs: ["source:dataset-a"]
                  params: {}
                prep_b:
                  operator: det_format_convert_to_coco
                  inputs: ["source:dataset-b"]
                  params: {}
                merge_all:
                  operator: det_merge_datasets
                  inputs: [prep_a, prep_b]
                  params: {}
        """)
        yaml_file = tmp_path / "multi.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        config = load_pipeline_config_from_yaml(yaml_file)

        assert len(config.tasks) == 3
        assert config.get_terminal_task_name() == "merge_all"
        assert set(config.get_all_source_dataset_ids()) == {"dataset-a", "dataset-b"}

        order = config.topological_order()
        assert order[-1] == "merge_all"

    def test_missing_pipeline_key_rejected(self, tmp_path: Path):
        """최상위 키가 'pipeline'이 아니면 ValueError."""
        yaml_content = "tasks:\n  t1:\n    operator: op\n    inputs: ['source:x']\n"
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        with pytest.raises(ValueError, match="최상위 키가 'pipeline'"):
            load_pipeline_config_from_yaml(yaml_file)

    def test_full_scenario_yaml(self, tmp_path: Path):
        """RAW → SOURCE 전체 시나리오 YAML."""
        yaml_content = textwrap.dedent("""\
            pipeline:
              name: "visdrone_coco_filtered"
              description: "VisDrone RAW → COCO SOURCE 변환"
              output:
                dataset_type: SOURCE
                annotation_format: COCO
                split: TRAIN
              tasks:
                convert_to_coco:
                  operator: det_format_convert_to_coco
                  inputs: ["source:550e8400-e29b-41d4-a716-446655440000"]
                  params:
                    category_names:
                      - pedestrian
                      - car
                      - van
                      - truck
                      - bus
                remap_classes:
                  operator: det_remap_class_name
                  inputs: [convert_to_coco]
                  params:
                    mapping:
                      van: car
                      truck: large_vehicle
                      bus: large_vehicle
                final_filter:
                  operator: filter_image_by_class
                  inputs: [remap_classes]
                  params:
                    mode: remove
                    class_names:
                      - ignored_region
                      - others
                    logic: any
        """)
        yaml_file = tmp_path / "scenario.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        config = load_pipeline_config_from_yaml(yaml_file)

        assert config.name == "visdrone_coco_filtered"
        assert len(config.tasks) == 3
        assert config.get_terminal_task_name() == "final_filter"

        order = config.topological_order()
        assert order == ["convert_to_coco", "remap_classes", "final_filter"]
        assert config.get_all_source_dataset_ids() == [
            "550e8400-e29b-41d4-a716-446655440000"
        ]
