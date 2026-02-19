"""
Pydantic 스키마 정의 - Manipulator & Pipeline
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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


# =============================================================================
# Pipeline 스키마
# =============================================================================

class ManipulatorConfig(BaseModel):
    """파이프라인 내 하나의 Manipulator 설정."""
    manipulator_name: str = Field(..., description="Manipulator.name")
    params: dict[str, Any] = Field(default_factory=dict)


class SourceConfig(BaseModel):
    """파이프라인 소스 데이터셋 설정."""
    dataset_id: str
    manipulators: list[ManipulatorConfig] = Field(default_factory=list)


class PipelineConfig(BaseModel):
    """파이프라인 실행 전체 설정."""
    sources: list[SourceConfig] = Field(..., min_length=1)
    post_merge_manipulators: list[ManipulatorConfig] = Field(default_factory=list)
    output_group_name: str
    output_dataset_type: str = Field(default="PROCESSED")
    output_annotation_format: str | None = None
    output_splits: list[str] = Field(default=["NONE"])
    description: str | None = None


class PipelineExecutionResponse(BaseModel):
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
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PipelineSubmitResponse(BaseModel):
    """파이프라인 제출 응답."""
    execution_id: str
    celery_task_id: str | None
    message: str


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
