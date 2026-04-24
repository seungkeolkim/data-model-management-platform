"""
Pydantic 스키마 정의 - Manipulator & Pipeline
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# 파이프라인 설정 스키마 — lib.pipeline.config에서 re-export
from lib.pipeline.config import (  # noqa: F401
    OutputConfig,
    PartialPipelineConfig,
    PipelineConfig,
    TaskConfig,
    load_pipeline_config_from_yaml,
)

# 파이프라인 검증 — lib.pipeline.pipeline_validator에서 re-export
from lib.pipeline.pipeline_validator import (  # noqa: F401
    PipelineValidationIssue,
    PipelineValidationResult,
    ValidationSeverity,
    validate_pipeline_config_static,
)

# =============================================================================
# Manipulator 스키마
# =============================================================================

class ManipulatorResponse(BaseModel):
    """Manipulator 응답."""
    id: str
    name: str
    category: str
    scope: list[str]
    compatible_task_types: list[str] | None
    compatible_annotation_fmts: list[str] | None
    output_annotation_fmt: str | None
    params_schema: dict[str, Any] | None
    description: str | None
    status: str
    version: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ManipulatorListResponse(BaseModel):
    items: list[ManipulatorResponse]
    total: int


class PipelineRunResponse(BaseModel):
    """파이프라인 실행 응답."""
    id: str
    output_dataset_id: str
    config: dict[str, Any] | None
    status: str
    current_stage: str | None
    processed_count: int
    total_count: int
    error_message: str | None
    celery_task_id: str | None
    task_progress: dict[str, Any] | None = None
    pipeline_image_url: str | None = None
    output_dataset_version: str | None = None
    output_dataset_group_id: str | None = None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PipelineValidationIssueResponse(BaseModel):
    """검증 문제 단건 응답."""
    severity: str = Field(..., description="error 또는 warning")
    code: str = Field(..., description="기계 판독용 오류 코드 (예: UNKNOWN_OPERATOR)")
    message: str = Field(..., description="사람이 읽을 수 있는 오류 메시지")
    field: str = Field(default="", description="문제 발생 위치 (예: tasks.merge.operator)")


class PipelineValidationResponse(BaseModel):
    """
    파이프라인 검증 응답.

    Web UI에서 실행 전 검증 결과를 표시하기 위한 구조.
    is_valid가 False이면 error 수준의 문제가 존재하여 실행 불가.
    """
    is_valid: bool = Field(..., description="검증 통과 여부 (error가 없으면 True)")
    error_count: int = Field(..., description="ERROR 수준 문제 수")
    warning_count: int = Field(..., description="WARNING 수준 문제 수")
    issues: list[PipelineValidationIssueResponse] = Field(
        default_factory=list,
        description="검증 문제 목록 (ERROR + WARNING 모두 포함)",
    )


class PipelineSubmitResponse(BaseModel):
    """파이프라인 제출 응답."""
    execution_id: str
    celery_task_id: str | None
    message: str


class PipelineListResponse(BaseModel):
    """파이프라인 실행 이력 목록 응답."""
    items: list[PipelineRunResponse]
    total: int


# =============================================================================
# Schema Preview (파이프라인 노드 시점별 head_schema 프리뷰)
# =============================================================================

class SchemaPreviewRequest(BaseModel):
    """
    특정 노드 시점의 head_schema 를 요청한다.

    Save 노드가 없는 부분 그래프에서도 프리뷰할 수 있도록
    PartialPipelineConfig 를 받는다. (output 필드 nullable)

    target_ref:
        - "task_{nodeId}" : operator/merge 노드의 출력
        - "source:{dataset_id}" : dataLoad 노드의 출력 (= 소스 자체의 head_schema)
    """
    config: PartialPipelineConfig
    target_ref: str = Field(..., description="task_<nodeId> 또는 source:<dataset_id>")


class SchemaPreviewHead(BaseModel):
    """head_schema 응답 항목."""
    name: str
    multi_label: bool
    classes: list[str]


class SchemaPreviewResponse(BaseModel):
    """프리뷰 응답.

    task_kind:
        "classification" | "detection" | "unknown"
    head_schema:
        classification 일 때만 채워진다. 이외엔 None.
    error:
        계산 실패 시 사용자 노출용 사유. 성공 시 None.
    """
    task_kind: str
    head_schema: list[SchemaPreviewHead] | None = None
    error_code: str | None = None
    error_message: str | None = None


# =============================================================================
# EDA 스키마
# =============================================================================

class EDAResult(BaseModel):
    """EDA 결과 요약."""
    dataset_id: str
    total_images: int
    total_annotations: int
    class_distribution: dict[str, int]
    image_size_stats: dict[str, Any]
    charts: list[str] = Field(default_factory=list, description="차트 이미지 URL 목록")
    completed_at: datetime | None = None


# =============================================================================
# System Status 스키마
# =============================================================================

class ServiceStatus(BaseModel):
    ok: bool
    error: str | None = None


class StorageStatus(ServiceStatus):
    backend: str
    base_path: str


class HealthResponse(BaseModel):
    status: str
    services: dict[str, Any]
    version: str
    env: str
