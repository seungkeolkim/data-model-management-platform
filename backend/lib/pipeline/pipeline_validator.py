"""
파이프라인 설정 검증기.

파이프라인 실행 전에 설정의 유효성을 검사하고,
문제가 발견되면 사유별 오류 메시지를 반환한다.

검증 레벨:
  - 정적 검증 (static): DB 접근 없이 config 자체만으로 검사 (lib/ 레이어)
    → operator 존재 여부, merge 입력 수, output 값 유효성, params 스키마 등
  - DB 검증 (database): DB 조회가 필요한 검사 (app/ 레이어에서 호출)
    → source dataset 존재 여부, dataset 상태, 출력 경로 충돌 등

Web UI에서는 실행 전 검증 단계에서 이 결과를 표시하여
사용자가 어떤 사유로 실패했는지 확인할 수 있다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from lib.manipulators import MANIPULATOR_REGISTRY
from lib.pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """검증 결과 심각도."""
    ERROR = "error"      # 실행 차단 — 이 문제가 해결되지 않으면 파이프라인 실행 불가
    WARNING = "warning"  # 경고 — 실행은 가능하지만 주의 필요


@dataclass
class PipelineValidationIssue:
    """
    단일 검증 문제.

    Web UI에서 사유별 오류 메시지를 표시하기 위한 구조체.
    field는 문제가 발생한 config 위치를 가리킨다.
    """
    severity: ValidationSeverity
    code: str        # 기계 판독용 코드 (예: "UNKNOWN_OPERATOR", "MERGE_MIN_INPUTS")
    message: str     # 사람이 읽을 수 있는 한글 메시지
    field: str = ""  # 문제 발생 위치 (예: "tasks.merge.operator", "output.dataset_type")


@dataclass
class PipelineValidationResult:
    """
    파이프라인 검증 결과.

    is_valid가 False이면 ERROR 수준의 문제가 1개 이상 존재한다.
    issues에 모든 문제(ERROR + WARNING)가 담긴다.
    """
    issues: list[PipelineValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """ERROR 수준의 문제가 없으면 유효하다고 판단."""
        return not any(
            issue.severity == ValidationSeverity.ERROR
            for issue in self.issues
        )

    @property
    def error_count(self) -> int:
        """ERROR 수준 문제 수."""
        return sum(
            1 for issue in self.issues
            if issue.severity == ValidationSeverity.ERROR
        )

    @property
    def warning_count(self) -> int:
        """WARNING 수준 문제 수."""
        return sum(
            1 for issue in self.issues
            if issue.severity == ValidationSeverity.WARNING
        )

    def add_error(self, code: str, message: str, issue_field: str = "") -> None:
        """ERROR 수준 문제를 추가한다."""
        self.issues.append(PipelineValidationIssue(
            severity=ValidationSeverity.ERROR,
            code=code,
            message=message,
            field=issue_field,
        ))

    def add_warning(self, code: str, message: str, issue_field: str = "") -> None:
        """WARNING 수준 문제를 추가한다."""
        self.issues.append(PipelineValidationIssue(
            severity=ValidationSeverity.WARNING,
            code=code,
            message=message,
            field=issue_field,
        ))

    def merge(self, other: PipelineValidationResult) -> None:
        """다른 검증 결과의 issues를 현재 결과에 합친다."""
        self.issues.extend(other.issues)


# =============================================================================
# 정적 검증 (DB 불필요)
# =============================================================================

# 허용되는 output.dataset_type 값
VALID_DATASET_TYPES = {"SOURCE", "PROCESSED", "FUSION"}

# 허용되는 output.split 값
VALID_SPLIT_VALUES = {"TRAIN", "VAL", "TEST", "NONE"}

# 허용되는 annotation_format 값
# CLS_MANIFEST 는 classification(manifest.jsonl + head_schema.json) 전용 포맷.
VALID_ANNOTATION_FORMATS = {"COCO", "YOLO", "CLS_MANIFEST"}


def validate_pipeline_config_static(config: PipelineConfig) -> PipelineValidationResult:
    """
    DB 접근 없이 PipelineConfig 자체만으로 수행하는 정적 검증.

    검증 항목:
      1. output.dataset_type 유효성
      2. output.split 유효성
      3. output.annotation_format 유효성
      4. 각 태스크의 operator가 MANIPULATOR_REGISTRY에 등록되어 있는지
      5. merge_datasets operator의 inputs가 2개 이상인지
      6. 단일 입력 전용 operator에 다중 입력이 주어지지 않았는지

    Args:
        config: 검증할 파이프라인 설정

    Returns:
        PipelineValidationResult — is_valid와 issues 목록을 포함
    """
    result = PipelineValidationResult()

    # (1) output.dataset_type 유효성
    _validate_output_dataset_type(config, result)

    # (2) output.split 유효성
    _validate_output_split(config, result)

    # (3) output.annotation_format 유효성
    _validate_output_annotation_format(config, result)

    # (4) operator 등록 여부
    _validate_operators_registered(config, result)

    # (5) merge_datasets 최소 입력 수
    _validate_merge_minimum_inputs(config, result)

    # (6) 단일 입력 전용 operator에 다중 입력 금지
    _validate_single_input_operators(config, result)

    # (7) required params 누락 검사
    _validate_required_params(config, result)

    return result


def _validate_output_dataset_type(
    config: PipelineConfig,
    result: PipelineValidationResult,
) -> None:
    """output.dataset_type이 허용된 값인지 검증한다."""
    dataset_type = config.output.dataset_type.upper()
    if dataset_type not in VALID_DATASET_TYPES:
        result.add_error(
            code="INVALID_DATASET_TYPE",
            message=(
                f"output.dataset_type '{config.output.dataset_type}'은(는) "
                f"허용되지 않는 값입니다. "
                f"사용 가능한 값: {', '.join(sorted(VALID_DATASET_TYPES))}"
            ),
            issue_field="output.dataset_type",
        )

    # RAW는 파이프라인으로 생성할 수 없음
    if dataset_type == "RAW":
        result.add_error(
            code="RAW_NOT_ALLOWED_AS_OUTPUT",
            message=(
                "RAW 타입은 파이프라인 출력으로 사용할 수 없습니다. "
                "RAW 데이터는 수동 업로드 후 GUI에서 등록해야 합니다."
            ),
            issue_field="output.dataset_type",
        )


def _validate_output_split(
    config: PipelineConfig,
    result: PipelineValidationResult,
) -> None:
    """output.split이 허용된 값인지 검증한다."""
    split_upper = config.output.split.upper()
    if split_upper not in VALID_SPLIT_VALUES:
        result.add_error(
            code="INVALID_SPLIT",
            message=(
                f"output.split '{config.output.split}'은(는) "
                f"허용되지 않는 값입니다. "
                f"사용 가능한 값: {', '.join(sorted(VALID_SPLIT_VALUES))}"
            ),
            issue_field="output.split",
        )


def _validate_output_annotation_format(
    config: PipelineConfig,
    result: PipelineValidationResult,
) -> None:
    """output.annotation_format이 유효한 값인지 검증한다."""
    annotation_format = config.output.annotation_format
    format_upper = annotation_format.upper()
    if format_upper not in VALID_ANNOTATION_FORMATS:
        result.add_error(
            code="INVALID_ANNOTATION_FORMAT",
            message=(
                f"output.annotation_format '{annotation_format}'은(는) "
                f"허용되지 않는 값입니다. "
                f"사용 가능한 값: {', '.join(sorted(VALID_ANNOTATION_FORMATS))}"
            ),
            issue_field="output.annotation_format",
        )


def _validate_operators_registered(
    config: PipelineConfig,
    result: PipelineValidationResult,
) -> None:
    """각 태스크의 operator가 MANIPULATOR_REGISTRY에 등록되어 있는지 검증한다."""
    registered_operator_names = set(MANIPULATOR_REGISTRY.keys())

    for task_name, task_config in config.tasks.items():
        if task_config.operator not in registered_operator_names:
            result.add_error(
                code="UNKNOWN_OPERATOR",
                message=(
                    f"태스크 '{task_name}'의 operator '{task_config.operator}'가 "
                    f"등록되지 않았습니다. "
                    f"사용 가능한 operator: {', '.join(sorted(registered_operator_names))}"
                ),
                issue_field=f"tasks.{task_name}.operator",
            )


def _validate_merge_minimum_inputs(
    config: PipelineConfig,
    result: PipelineValidationResult,
) -> None:
    """merge_datasets operator의 inputs가 2개 이상인지 검증한다."""
    for task_name, task_config in config.tasks.items():
        if task_config.operator == "merge_datasets" and len(task_config.inputs) < 2:
            result.add_error(
                code="MERGE_MIN_INPUTS",
                message=(
                    f"태스크 '{task_name}'의 merge_datasets operator는 "
                    f"최소 2개 이상의 입력이 필요합니다. "
                    f"현재 입력 수: {len(task_config.inputs)}"
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )


def _validate_required_params(
    config: PipelineConfig,
    result: PipelineValidationResult,
) -> None:
    """
    required params가 비어있는 태스크를 경고한다.

    params_schema DB 조회 없이, 각 manipulator 클래스의 REQUIRED_PARAMS를 참조한다.
    REQUIRED_PARAMS가 정의되지 않은 클래스는 검사를 건너뛴다.
    """
    for task_name, task_config in config.tasks.items():
        manipulator_class = MANIPULATOR_REGISTRY.get(task_config.operator)
        if manipulator_class is None:
            continue

        required_param_names: list[str] = getattr(manipulator_class, "REQUIRED_PARAMS", [])
        for param_name in required_param_names:
            param_value = task_config.params.get(param_name)
            # None, 빈 문자열, 빈 dict, 빈 list 모두 누락으로 판단
            if not param_value:
                result.add_error(
                    code="MISSING_REQUIRED_PARAM",
                    message=(
                        f"'{param_name}' 설정값이 비어있습니다. 값을 입력해 주세요."
                    ),
                    issue_field=f"tasks.{task_name}.params.{param_name}",
                )


def _validate_single_input_operators(
    config: PipelineConfig,
    result: PipelineValidationResult,
) -> None:
    """
    multi-input을 지원하지 않는 operator에 다중 입력이 주어졌는지 검증한다.

    accepts_multi_input = True인 operator만 다중 입력을 받을 수 있다.
    그 외 operator에 2개 이상의 입력이 주어지면 경고한다.
    (기존 _merge_metas() 폴백이 있어 실행은 되지만, 의도한 동작이 아닐 수 있음)
    """
    for task_name, task_config in config.tasks.items():
        if len(task_config.inputs) <= 1:
            continue

        manipulator_class = MANIPULATOR_REGISTRY.get(task_config.operator)
        if manipulator_class is None:
            # operator 자체가 등록되지 않은 경우는 _validate_operators_registered에서 처리
            continue

        accepts_multi_input = getattr(manipulator_class, "accepts_multi_input", False)
        if not accepts_multi_input:
            result.add_warning(
                code="MULTI_INPUT_WITHOUT_MERGE",
                message=(
                    f"태스크 '{task_name}'의 operator '{task_config.operator}'는 "
                    f"다중 입력 전용이 아닌데 {len(task_config.inputs)}개의 입력이 주어졌습니다. "
                    f"입력들이 자동으로 단순 병합됩니다. "
                    f"명시적인 merge_datasets 사용을 권장합니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )
