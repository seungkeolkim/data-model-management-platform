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
# PipelineFamily / Pipeline (concept) / PipelineVersion 스키마 (v7.11)
# =============================================================================

class PipelineFamilyResponse(BaseModel):
    """PipelineFamily 응답 — 즐겨찾기 폴더."""
    id: str
    name: str
    description: str | None
    color: str = Field(
        ...,
        description="Family 시각 구분 색 (`#RRGGBB`)",
    )
    pipeline_count: int = Field(
        default=0,
        description="이 family 에 묶인 active Pipeline 수",
    )
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineFamilyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="`#RRGGBB`. 미지정 시 backend 가 랜덤 할당.",
    )


class PipelineFamilyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="`#RRGGBB`. 미지정 시 변경 안 함.",
    )


class PipelineVersionSummary(BaseModel):
    """PipelineVersion 요약 — concept 응답 안에서 versions 목록 행."""
    id: str
    version: str
    is_active: bool
    has_automation: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineResponse(BaseModel):
    """Pipeline (concept) 응답 — versions 목록 포함."""
    id: str
    family_id: str | None
    family_name: str | None = None
    name: str
    description: str | None
    output_split_id: str
    output_group_id: str | None = Field(
        default=None,
        description="output_split 의 상위 group id",
    )
    output_group_name: str | None = None
    output_split: str | None = Field(
        default=None,
        description="TRAIN | VAL | TEST | NONE — DatasetSplit.split 문자열",
    )
    task_type: str
    is_active: bool
    versions: list[PipelineVersionSummary] = Field(default_factory=list)
    latest_version: PipelineVersionSummary | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineListItemResponse(BaseModel):
    """Pipeline 목록 행 응답 — versions 카운트만, 본문 X."""
    id: str
    family_id: str | None
    family_name: str | None = None
    name: str
    description: str | None
    output_split_id: str
    output_group_id: str | None = None
    output_group_name: str | None = None
    output_split: str | None = None
    task_type: str
    is_active: bool
    version_count: int = Field(default=0, description="누적 PipelineVersion 수")
    latest_version: str | None = Field(
        default=None, description="최신 active version 문자열 (없으면 null)",
    )
    has_automation: bool = False
    run_count: int = Field(default=0, description="이 concept 모든 version 의 누적 run 수")
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineListPageResponse(BaseModel):
    items: list[PipelineListItemResponse]
    total: int
    limit: int
    offset: int


class PipelineUpdateRequest(BaseModel):
    """
    Pipeline (concept) 편집 — name / description / family_id / is_active.
    config 는 immutable, version 단위 책임.
    """
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    family_id: str | None = Field(
        default=None,
        description="이 Pipeline 을 옮길 family. 명시 시 family 변경",
    )
    unset_family: bool = Field(
        default=False,
        description="True 이면 family_id 를 NULL 로 (미분류). family_id 와 동시 지정 X",
    )
    is_active: bool | None = Field(
        default=None, description="soft delete 토글. FALSE 로 전환하면 모든 version automation / run 차단",
    )


class PipelineVersionResponse(BaseModel):
    """PipelineVersion 상세 — config + 모 Pipeline 메타."""
    id: str
    pipeline_id: str
    pipeline_name: str
    family_id: str | None
    family_name: str | None = None
    version: str
    config: dict[str, Any]
    task_type: str
    output_split_id: str
    output_group_id: str | None = None
    output_group_name: str | None = None
    output_split: str | None = None
    is_active: bool
    has_automation: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineVersionUpdateRequest(BaseModel):
    """PipelineVersion 편집 — is_active 토글만 (config immutable)."""
    is_active: bool | None = None


# =============================================================================
# PipelineRun 제출 (Version Resolver Modal — 027 §4-3)
# =============================================================================

class PipelineRunSubmitRequest(BaseModel):
    """
    `POST /pipelines/{id}/runs` 요청 바디.

    resolved_input_versions — `{split_id: version}`. 사용자가 각 source split 의
    version 을 드롭다운에서 선택해 확정. 기본값 (UI 에서 채움) = 각 split 의 최신 version.
    """
    resolved_input_versions: dict[str, str] = Field(
        default_factory=dict,
        description="{split_id: version} — run 시점 input 해석 맵",
    )


# =============================================================================
# PipelineAutomation 스키마 (§2-3 + §12-3 soft delete)
# =============================================================================

class PipelineAutomationResponse(BaseModel):
    id: str
    pipeline_version_id: str
    pipeline_id: str | None = Field(
        default=None,
        description="모 Pipeline (concept) id — 조회 편의 (selectinload 시 채움)",
    )
    pipeline_name: str | None = None
    pipeline_version: str | None = None
    status: str
    mode: str | None
    poll_interval: str | None
    error_reason: str | None
    last_seen_input_versions: dict[str, Any] | None
    is_active: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineAutomationUpsertRequest(BaseModel):
    """
    자동화 등록 / 업데이트 요청. `POST /pipelines/{id}/automation` 또는 PATCH.

    Pipeline 당 is_active=TRUE 인 자동화는 최대 1개 (partial unique index 강제).
    같은 Pipeline 에 다시 POST 하면 기존 active 행을 덮어쓴다.
    """
    status: str = Field(default="stopped", description="stopped | active | error")
    mode: str | None = Field(default=None, description="polling | triggering | NULL")
    poll_interval: str | None = Field(
        default=None, description="10m | 1h | 6h | 24h | NULL (polling 외)",
    )


class PipelineAutomationRerunRequest(BaseModel):
    """
    수동 재실행 요청 — 026 §5-2a 2-버튼 UX.

    - if_delta: 상류 delta 판정 후 있으면 dispatch, 없으면 SKIPPED_NO_DELTA
    - force_latest: delta 무시, 각 source split 의 최신 version 으로 항상 dispatch
    """
    mode: str = Field(
        default="if_delta",
        description="if_delta | force_latest",
    )


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
