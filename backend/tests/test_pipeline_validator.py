"""
파이프라인 검증기 단위 테스트.

validate_pipeline_config_static()의 정적 검증 항목을 테스트한다.
DB 의존 검증은 이 테스트의 범위 밖이다 (통합 테스트에서 다룸).
"""
from __future__ import annotations

import pytest

from lib.pipeline.config import PipelineConfig
from lib.pipeline.pipeline_validator import (
    PipelineValidationResult,
    ValidationSeverity,
    validate_pipeline_config_static,
)


def _make_config(
    name: str = "test_pipeline",
    dataset_type: str = "PROCESSED",
    annotation_format: str = "COCO",
    split: str = "TRAIN",
    tasks: dict | None = None,
) -> PipelineConfig:
    """테스트용 PipelineConfig를 간편하게 생성하는 헬퍼."""
    if tasks is None:
        tasks = {
            "convert": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            }
        }
    return PipelineConfig(
        name=name,
        output={
            "dataset_type": dataset_type,
            "annotation_format": annotation_format,
            "split": split,
        },
        tasks=tasks,
    )


# =============================================================================
# PipelineValidationResult 기본 동작
# =============================================================================


class TestPipelineValidationResult:
    """PipelineValidationResult 모델의 기본 동작을 검증한다."""

    def test_empty_result_is_valid(self):
        """issues가 비어있으면 is_valid는 True여야 한다."""
        result = PipelineValidationResult()
        assert result.is_valid is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_error_makes_invalid(self):
        """ERROR가 하나라도 있으면 is_valid는 False여야 한다."""
        result = PipelineValidationResult()
        result.add_error("TEST_ERROR", "테스트 에러")
        assert result.is_valid is False
        assert result.error_count == 1

    def test_warning_only_is_still_valid(self):
        """WARNING만 있으면 is_valid는 True여야 한다."""
        result = PipelineValidationResult()
        result.add_warning("TEST_WARNING", "테스트 경고")
        assert result.is_valid is True
        assert result.warning_count == 1

    def test_merge_combines_issues(self):
        """merge()는 두 결과의 issues를 합쳐야 한다."""
        result_a = PipelineValidationResult()
        result_a.add_error("ERROR_A", "에러 A")

        result_b = PipelineValidationResult()
        result_b.add_warning("WARN_B", "경고 B")

        result_a.merge(result_b)
        assert len(result_a.issues) == 2
        assert result_a.error_count == 1
        assert result_a.warning_count == 1


# =============================================================================
# output.dataset_type 검증
# =============================================================================


class TestValidateOutputDatasetType:
    """output.dataset_type 관련 검증을 테스트한다."""

    @pytest.mark.parametrize("dataset_type", ["SOURCE", "PROCESSED", "FUSION"])
    def test_valid_dataset_types_pass(self, dataset_type: str):
        """허용된 dataset_type은 오류가 없어야 한다."""
        config = _make_config(dataset_type=dataset_type)
        result = validate_pipeline_config_static(config)
        error_codes = [issue.code for issue in result.issues if issue.severity == ValidationSeverity.ERROR]
        assert "INVALID_DATASET_TYPE" not in error_codes
        assert "RAW_NOT_ALLOWED_AS_OUTPUT" not in error_codes

    def test_invalid_dataset_type_detected(self):
        """허용되지 않는 dataset_type은 INVALID_DATASET_TYPE 오류가 발생해야 한다."""
        config = _make_config(dataset_type="UNKNOWN_TYPE")
        result = validate_pipeline_config_static(config)
        assert not result.is_valid
        error_codes = [issue.code for issue in result.issues]
        assert "INVALID_DATASET_TYPE" in error_codes

    def test_raw_type_not_allowed_as_output(self):
        """RAW 타입은 파이프라인 출력으로 사용 불가해야 한다."""
        config = _make_config(dataset_type="RAW")
        result = validate_pipeline_config_static(config)
        assert not result.is_valid
        error_codes = [issue.code for issue in result.issues]
        assert "RAW_NOT_ALLOWED_AS_OUTPUT" in error_codes


# =============================================================================
# output.split 검증
# =============================================================================


class TestValidateOutputSplit:
    """output.split 관련 검증을 테스트한다."""

    @pytest.mark.parametrize("split", ["TRAIN", "VAL", "TEST", "NONE"])
    def test_valid_splits_pass(self, split: str):
        """허용된 split 값은 오류가 없어야 한다."""
        config = _make_config(split=split)
        result = validate_pipeline_config_static(config)
        error_codes = [issue.code for issue in result.issues]
        assert "INVALID_SPLIT" not in error_codes

    def test_invalid_split_detected(self):
        """허용되지 않는 split 값은 INVALID_SPLIT 오류가 발생해야 한다."""
        config = _make_config(split="INVALID")
        result = validate_pipeline_config_static(config)
        assert not result.is_valid
        error_codes = [issue.code for issue in result.issues]
        assert "INVALID_SPLIT" in error_codes


# =============================================================================
# output.annotation_format 검증
# =============================================================================


class TestValidateOutputAnnotationFormat:
    """output.annotation_format 관련 검증을 테스트한다."""

    @pytest.mark.parametrize("annotation_format", ["COCO", "YOLO"])
    def test_valid_formats_pass(self, annotation_format: str):
        """허용된 포맷은 오류가 없어야 한다."""
        config = _make_config(annotation_format=annotation_format)
        result = validate_pipeline_config_static(config)
        error_codes = [issue.code for issue in result.issues]
        assert "INVALID_ANNOTATION_FORMAT" not in error_codes

    def test_invalid_format_detected(self):
        """허용되지 않는 포맷은 INVALID_ANNOTATION_FORMAT 오류가 발생해야 한다."""
        config = _make_config(annotation_format="XML")
        result = validate_pipeline_config_static(config)
        assert not result.is_valid
        error_codes = [issue.code for issue in result.issues]
        assert "INVALID_ANNOTATION_FORMAT" in error_codes


# =============================================================================
# operator 등록 여부 검증
# =============================================================================


class TestValidateOperatorsRegistered:
    """operator 등록 여부 검증을 테스트한다."""

    def test_registered_operator_passes(self):
        """MANIPULATOR_REGISTRY에 등록된 operator는 오류가 없어야 한다."""
        config = _make_config(tasks={
            "convert": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            }
        })
        result = validate_pipeline_config_static(config)
        error_codes = [issue.code for issue in result.issues]
        assert "UNKNOWN_OPERATOR" not in error_codes

    def test_unregistered_operator_detected(self):
        """등록되지 않은 operator는 UNKNOWN_OPERATOR 오류가 발생해야 한다."""
        config = _make_config(tasks={
            "bad_task": {
                "operator": "nonexistent_operator",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            }
        })
        result = validate_pipeline_config_static(config)
        assert not result.is_valid
        error_codes = [issue.code for issue in result.issues]
        assert "UNKNOWN_OPERATOR" in error_codes

    def test_error_message_includes_available_operators(self):
        """오류 메시지에 사용 가능한 operator 목록이 포함되어야 한다."""
        config = _make_config(tasks={
            "bad_task": {
                "operator": "nonexistent_operator",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            }
        })
        result = validate_pipeline_config_static(config)
        unknown_error = next(
            issue for issue in result.issues if issue.code == "UNKNOWN_OPERATOR"
        )
        assert "det_format_convert_to_coco" in unknown_error.message
        assert "det_merge_datasets" in unknown_error.message

    def test_error_field_points_to_correct_task(self):
        """오류의 field가 문제 태스크를 정확히 가리켜야 한다."""
        config = _make_config(tasks={
            "bad_task": {
                "operator": "nonexistent_operator",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            }
        })
        result = validate_pipeline_config_static(config)
        unknown_error = next(
            issue for issue in result.issues if issue.code == "UNKNOWN_OPERATOR"
        )
        assert unknown_error.field == "tasks.bad_task.operator"


# =============================================================================
# det_merge_datasets 최소 입력 수 검증
# =============================================================================


class TestValidateMergeMinimumInputs:
    """det_merge_datasets의 최소 입력 수 검증을 테스트한다."""

    def test_merge_with_two_inputs_passes(self):
        """det_merge_datasets에 2개 입력이면 오류가 없어야 한다."""
        config = _make_config(tasks={
            "convert_a": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            },
            "convert_b": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000002"],
                "params": {},
            },
            "merge": {
                "operator": "det_merge_datasets",
                "inputs": ["convert_a", "convert_b"],
                "params": {},
            },
        })
        result = validate_pipeline_config_static(config)
        error_codes = [issue.code for issue in result.issues]
        assert "MERGE_MIN_INPUTS" not in error_codes

    def test_merge_with_one_input_detected(self):
        """det_merge_datasets에 1개 입력이면 MERGE_MIN_INPUTS 오류가 발생해야 한다."""
        config = _make_config(tasks={
            "convert_a": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            },
            "merge": {
                "operator": "det_merge_datasets",
                "inputs": ["convert_a"],
                "params": {},
            },
        })
        result = validate_pipeline_config_static(config)
        assert not result.is_valid
        error_codes = [issue.code for issue in result.issues]
        assert "MERGE_MIN_INPUTS" in error_codes


# =============================================================================
# 단일 입력 전용 operator에 다중 입력 경고
# =============================================================================


class TestValidateSingleInputOperators:
    """단일 입력 전용 operator에 다중 입력 시 경고 검증을 테스트한다."""

    def test_single_input_operator_with_one_input_no_warning(self):
        """단일 입력 operator에 1개 입력이면 경고가 없어야 한다."""
        config = _make_config(tasks={
            "convert": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            }
        })
        result = validate_pipeline_config_static(config)
        warning_codes = [
            issue.code for issue in result.issues
            if issue.severity == ValidationSeverity.WARNING
        ]
        assert "MULTI_INPUT_WITHOUT_MERGE" not in warning_codes

    def test_single_input_operator_with_multi_inputs_warns(self):
        """단일 입력 operator에 다중 입력이면 MULTI_INPUT_WITHOUT_MERGE 경고가 발생해야 한다."""
        config = _make_config(tasks={
            "convert_a": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            },
            "convert_b": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000002"],
                "params": {},
            },
            # det_format_convert_to_yolo는 단일 입력 전용인데 2개 입력
            "bad_multi": {
                "operator": "det_format_convert_to_yolo",
                "inputs": ["convert_a", "convert_b"],
                "params": {},
            },
        })
        result = validate_pipeline_config_static(config)
        # WARNING이므로 is_valid는 여전히 True
        assert result.is_valid is True
        warning_codes = [
            issue.code for issue in result.issues
            if issue.severity == ValidationSeverity.WARNING
        ]
        assert "MULTI_INPUT_WITHOUT_MERGE" in warning_codes

    def test_multi_input_operator_with_multi_inputs_no_warning(self):
        """multi-input 전용 operator(det_merge_datasets)에 다중 입력이면 경고가 없어야 한다."""
        config = _make_config(tasks={
            "convert_a": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                "params": {},
            },
            "convert_b": {
                "operator": "det_format_convert_to_coco",
                "inputs": ["source:00000000-0000-0000-0000-000000000002"],
                "params": {},
            },
            "merge": {
                "operator": "det_merge_datasets",
                "inputs": ["convert_a", "convert_b"],
                "params": {},
            },
        })
        result = validate_pipeline_config_static(config)
        warning_codes = [
            issue.code for issue in result.issues
            if issue.severity == ValidationSeverity.WARNING
        ]
        assert "MULTI_INPUT_WITHOUT_MERGE" not in warning_codes


# =============================================================================
# 복합 시나리오
# =============================================================================


class TestComplexValidationScenarios:
    """여러 검증 항목이 동시에 걸리는 복합 시나리오를 테스트한다."""

    def test_multiple_errors_collected(self):
        """여러 문제가 동시에 존재하면 모두 수집되어야 한다."""
        config = _make_config(
            dataset_type="INVALID_TYPE",
            split="INVALID_SPLIT",
            annotation_format="XML",
            tasks={
                "bad_task": {
                    "operator": "nonexistent_operator",
                    "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                    "params": {},
                }
            },
        )
        result = validate_pipeline_config_static(config)
        assert not result.is_valid
        error_codes = {issue.code for issue in result.issues if issue.severity == ValidationSeverity.ERROR}
        assert "INVALID_DATASET_TYPE" in error_codes
        assert "INVALID_SPLIT" in error_codes
        assert "INVALID_ANNOTATION_FORMAT" in error_codes
        assert "UNKNOWN_OPERATOR" in error_codes

    def test_valid_merge_pipeline_passes_all(self):
        """정상적인 merge 파이프라인은 검증을 통과해야 한다."""
        config = _make_config(
            dataset_type="FUSION",
            annotation_format="COCO",
            split="VAL",
            tasks={
                "convert_a": {
                    "operator": "det_format_convert_to_coco",
                    "inputs": ["source:00000000-0000-0000-0000-000000000001"],
                    "params": {},
                },
                "convert_b": {
                    "operator": "det_format_convert_to_coco",
                    "inputs": ["source:00000000-0000-0000-0000-000000000002"],
                    "params": {},
                },
                "merge": {
                    "operator": "det_merge_datasets",
                    "inputs": ["convert_a", "convert_b"],
                    "params": {},
                },
            },
        )
        result = validate_pipeline_config_static(config)
        assert result.is_valid is True
        assert result.error_count == 0
