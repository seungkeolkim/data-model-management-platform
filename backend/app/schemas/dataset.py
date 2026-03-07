"""
Pydantic 스키마 정의 - Dataset / DatasetGroup
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# =============================================================================
# 허용 상수
# =============================================================================

# 데이터셋 task 유형 (DB: task_types JSONB 컬럼)
ALLOWED_TASK_TYPES = Literal[
    "DETECTION",           # 객체 탐지
    "SEGMENTATION",        # 세그멘테이션
    "CLASSIFICATION",      # 이미지 분류
    "ATTR_CLASSIFICATION", # 속성 분류
    "ZERO_SHOT",           # 제로샷
]

# 어노테이션 포맷 (DB: annotation_format 컬럼)
ALLOWED_ANNOTATION_FORMATS = Literal[
    "COCO",        # COCO JSON
    "YOLO",        # YOLO txt
    "ATTR_JSON",   # 속성 JSON (커스텀)
    "CLS_FOLDER",  # 분류 폴더 구조
    "CUSTOM",      # 기타 커스텀
    "NONE",        # 미지정
]

ALLOWED_SPLITS = Literal["TRAIN", "VAL", "TEST", "NONE"]


# =============================================================================
# DatasetGroup 스키마
# =============================================================================

class DatasetGroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="데이터셋 그룹명")
    dataset_type: str = Field(
        ...,
        description="데이터셋 원본 유형: RAW | SOURCE | PROCESSED | FUSION",
    )
    annotation_format: str = Field(
        default="NONE",
        description="COCO | YOLO | ATTR_JSON | CLS_FOLDER | CUSTOM | NONE",
    )
    task_types: list[str] | None = Field(
        default=None,
        description="사용 목적: DETECTION | SEGMENTATION | CLASSIFICATION | ATTR_CLASSIFICATION | ZERO_SHOT",
    )
    modality: str = Field(default="RGB")
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
    """
    GUI Dataset 등록 요청.
    - task_types: 사용자가 드롭다운으로 선택 (DETECTION / SEGMENTATION / CLASSIFICATION 등)
    - annotation_format: 등록 후 선택 (COCO / YOLO / ATTR_JSON / CLS_FOLDER / CUSTOM / NONE)
    - storage_uri: NAS 마운트 기준 상대경로 (예: raw/my_dataset/train/v1.0.0)
    - 경로 존재 여부만 검사. annotation 정합성 체크는 별도 단계에서 수행.
    """
    # 그룹 정보
    group_id: str | None = Field(default=None, description="기존 그룹 ID (새 그룹이면 None)")
    group_name: str | None = Field(default=None, description="새 그룹 생성 시 그룹명")

    # 사용 목적 (드롭다운 선택)
    task_types: list[str] = Field(
        ...,
        description="사용 목적 (DETECTION | SEGMENTATION | CLASSIFICATION | ATTR_CLASSIFICATION | ZERO_SHOT)",
    )

    # 어노테이션 포맷 (등록 후 선택, 미정이면 NONE)
    annotation_format: str = Field(
        default="NONE",
        description="COCO | YOLO | ATTR_JSON | CLS_FOLDER | CUSTOM | NONE",
    )

    modality: str = Field(default="RGB")
    source_origin: str | None = None
    description: str | None = None

    # Dataset(split/version) 정보
    split: ALLOWED_SPLITS = Field(default="NONE", description="TRAIN | VAL | TEST | NONE")
    version: str | None = Field(default=None, description="미입력 시 v1.0.0 자동 생성")

    # NAS 경로 (LOCAL_STORAGE_BASE 기준 상대경로)
    storage_uri: str = Field(
        ...,
        description="NAS 마운트 기준 상대경로 (예: raw/my_dataset/train/v1.0.0)",
    )

    @model_validator(mode="after")
    def check_group_identifier(self) -> "DatasetRegisterRequest":
        if not self.group_id and not self.group_name:
            raise ValueError("group_id 또는 group_name 중 하나는 필수입니다.")
        return self


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
    # COCO 검증 결과
    coco_valid: bool = False
    coco_categories: list[str] = []
    coco_annotation_count: int = 0
    error: str | None = None


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
    source: str
    target: str
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
