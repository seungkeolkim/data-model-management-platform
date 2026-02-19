"""
Pydantic 스키마 정의 - Dataset Group
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# DatasetGroup 스키마
# =============================================================================

class DatasetGroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="데이터셋 그룹명")
    dataset_type: str = Field(..., description="RAW | SOURCE | PROCESSED | FUSION")
    annotation_format: str = Field(default="NONE", description="COCO | YOLO | ATTR_JSON | CLS_FOLDER | CUSTOM | NONE")
    task_types: list[str] | None = Field(default=None, description="태스크 유형 목록")
    modality: str = Field(default="RGB", description="RGB | THERMAL | DEPTH | MULTISPECTRAL")
    source_origin: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None)
    extra: dict[str, Any] | None = Field(default=None)


class DatasetGroupCreate(DatasetGroupBase):
    """데이터셋 그룹 생성 요청."""
    pass


class DatasetGroupUpdate(BaseModel):
    """데이터셋 그룹 수정 요청 (부분 업데이트)."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    annotation_format: str | None = None
    task_types: list[str] | None = None
    modality: str | None = None
    source_origin: str | None = None
    description: str | None = None
    extra: dict[str, Any] | None = None


class DatasetSummary(BaseModel):
    """DatasetGroup 내 Dataset 요약 (목록 조회용)."""
    id: str
    split: str
    version: str
    status: str
    image_count: int | None
    class_count: int | None
    storage_uri: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DatasetGroupResponse(DatasetGroupBase):
    """데이터셋 그룹 응답."""
    id: str
    created_at: datetime
    updated_at: datetime
    datasets: list[DatasetSummary] = []

    model_config = {"from_attributes": True}


class DatasetGroupListResponse(BaseModel):
    """데이터셋 그룹 목록 응답."""
    items: list[DatasetGroupResponse]
    total: int
    page: int
    page_size: int


# =============================================================================
# Dataset 스키마
# =============================================================================

class DatasetBase(BaseModel):
    split: str = Field(default="NONE", description="TRAIN | VAL | TEST | NONE")
    version: str = Field(..., description="v1.0.0 형식")
    annotation_format: str | None = Field(default=None)
    storage_uri: str = Field(..., description="NAS 상대경로")
    status: str = Field(default="PENDING")
    image_count: int | None = None
    class_count: int | None = None


class DatasetCreate(DatasetBase):
    """Dataset 생성 요청."""
    group_id: str


class DatasetRegisterRequest(BaseModel):
    """GUI Dataset 등록 요청 (NAS 경로 지정 방식)."""
    # 그룹 정보 (새 그룹 생성 또는 기존 그룹에 추가)
    group_id: str | None = Field(default=None, description="기존 그룹에 추가 시")
    group_name: str | None = Field(default=None, description="새 그룹 생성 시")
    dataset_type: str = Field(..., description="RAW | SOURCE | PROCESSED | FUSION")
    annotation_format: str = Field(default="NONE")
    task_types: list[str] | None = None
    modality: str = Field(default="RGB")
    source_origin: str | None = None
    description: str | None = None

    # Dataset (split/version) 정보
    split: str = Field(default="NONE", description="TRAIN | VAL | TEST | NONE")
    version: str | None = Field(default=None, description="미입력 시 자동 생성 (v1.0.0)")
    storage_uri: str = Field(..., description="NAS 상대경로 (예: raw/my_dataset/train/v1.0.0)")


class DatasetResponse(DatasetBase):
    """Dataset 응답."""
    id: str
    group_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DatasetValidateRequest(BaseModel):
    """NAS 경로 유효성 검사 요청."""
    storage_uri: str


class DatasetValidateResponse(BaseModel):
    """NAS 경로 유효성 검사 응답."""
    storage_uri: str
    path_exists: bool
    images_dir_exists: bool
    annotation_exists: bool
    image_count: int


# =============================================================================
# Lineage 스키마
# =============================================================================

class LineageCreate(BaseModel):
    parent_id: str
    child_id: str
    transform_config: dict[str, Any] | None = None


class LineageResponse(BaseModel):
    id: str
    parent_id: str
    child_id: str
    transform_config: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LineageNodeResponse(BaseModel):
    """Lineage 그래프 노드 응답 (React Flow 형식)."""
    id: str
    dataset_id: str
    group_name: str
    split: str
    version: str
    dataset_type: str
    status: str
    image_count: int | None


class LineageEdgeResponse(BaseModel):
    """Lineage 그래프 엣지 응답."""
    id: str
    source: str  # parent dataset id
    target: str  # child dataset id
    transform_config: dict[str, Any] | None


class LineageGraphResponse(BaseModel):
    """Lineage 전체 그래프 응답."""
    nodes: list[LineageNodeResponse]
    edges: list[LineageEdgeResponse]


# =============================================================================
# 공통 응답
# =============================================================================

class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
