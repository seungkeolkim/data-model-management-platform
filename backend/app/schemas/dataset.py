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
# CLASSIFICATION은 단일 라벨/다중 head 이미지 분류를 모두 포함한다.
# 구 ATTR_CLASSIFICATION은 CLASSIFICATION으로 통합되어 제거됨 (migration 008).
ALLOWED_TASK_TYPES = Literal[
    "DETECTION",           # 객체 탐지
    "SEGMENTATION",        # 세그멘테이션
    "CLASSIFICATION",      # 이미지 분류 (단일/다중 head 포함)
    "ZERO_SHOT",           # 제로샷
]

# 어노테이션 포맷 (DB: annotation_format 컬럼)
ALLOWED_ANNOTATION_FORMATS = Literal[
    "COCO",        # COCO JSON
    "YOLO",        # YOLO txt
    "ATTR_JSON",   # 속성 JSON (커스텀)
    "CLS_MANIFEST",  # Classification: 단일 풀 + manifest.jsonl + head_schema.json
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
        description="COCO | YOLO | ATTR_JSON | CLS_MANIFEST | CUSTOM | NONE",
    )
    task_types: list[str] | None = Field(
        default=None,
        description="사용 목적: DETECTION | SEGMENTATION | CLASSIFICATION | ZERO_SHOT",
    )
    modality: str = Field(default="RGB")
    source_origin: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None)
    extra: dict[str, Any] | None = Field(default=None)
    # classification 전용. head/class 계약(SSOT). 그 외 task 그룹은 None.
    head_schema: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Classification 전용 head/class 계약. "
            '예: {"heads":[{"name":"...","multi_label":false,"classes":[...]}]}'
        ),
    )


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
    annotation_format: str | None
    storage_uri: str
    annotation_files: list[str] | None
    annotation_meta_file: str | None = None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    pipeline_execution_id: str | None = None
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
    version: str = Field(..., description="{major}.{minor} 형식 (예: 1.0, 2.0)")
    annotation_format: str | None = Field(default=None)
    storage_uri: str = Field(..., description="NAS 상대경로")
    status: str = Field(default="PENDING")
    image_count: int | None = None
    class_count: int | None = None
    annotation_files: list[str] | None = None
    annotation_meta_file: str | None = None


class DatasetCreate(DatasetBase):
    """Dataset 생성 요청."""
    group_id: str


class DatasetRegisterRequest(BaseModel):
    """
    GUI Dataset 등록 요청 (파일 브라우저 방식).
    - source_image_dir: 이미지 폴더 절대경로 (LOCAL_BROWSE_ROOTS 중 하나의 하위여야 함)
    - source_annotation_files: 어노테이션 파일 절대경로 목록
    - 플랫폼이 파일을 관리 스토리지로 복사하고, 버전을 자동 생성함
    """
    # 그룹 정보
    group_id: str | None = Field(default=None, description="기존 그룹 ID (새 그룹이면 None)")
    group_name: str | None = Field(default=None, description="새 그룹 생성 시 그룹명")

    # 사용 목적 (등록 UI는 단일 선택이므로 정확히 1개 원소여야 함).
    # 컬럼은 list로 유지하여 추후 '추가 지원 용도' 멀티선택 도입 시 확장 가능.
    task_types: list[str] = Field(
        ...,
        min_length=1,
        max_length=1,
        description="사용 목적 (단일 원소 리스트). DETECTION | SEGMENTATION | CLASSIFICATION | ZERO_SHOT",
    )

    # 어노테이션 포맷 (등록 후 선택, 미정이면 NONE)
    annotation_format: str = Field(
        default="NONE",
        description="COCO | YOLO | ATTR_JSON | CLS_MANIFEST | CUSTOM | NONE",
    )

    modality: str = Field(default="RGB")
    source_origin: str | None = None
    description: str | None = None

    # Dataset(split/version) 정보
    split: ALLOWED_SPLITS = Field(default="NONE", description="TRAIN | VAL | TEST | NONE")

    # 소스 파일 경로 (LOCAL_BROWSE_ROOTS 하위 절대경로)
    source_image_dir: str = Field(
        ...,
        description="이미지 폴더 절대경로 (예: /home/user/uploads/my_data/images)",
    )
    source_annotation_files: list[str] = Field(
        ...,
        min_length=1,
        description="어노테이션 파일 절대경로 목록",
    )
    source_annotation_meta_file: str | None = Field(
        default=None,
        description="어노테이션 메타 파일 절대경로 (예: data.yaml). YOLO 포맷 등에서 클래스 매핑 파일",
    )

    @model_validator(mode="after")
    def check_group_identifier(self) -> DatasetRegisterRequest:
        if not self.group_id and not self.group_name:
            raise ValueError("group_id 또는 group_name 중 하나는 필수입니다.")
        return self


# =============================================================================
# Classification 등록 스키마
# =============================================================================
# Classification은 어노테이션 파일 대신 폴더 구조(head/class/이미지)로 라벨이
# 결정되므로 별도 요청 스키마를 둔다. 등록 시 단일 풀 + manifest.jsonl로 정규화한다.
#
# 이미지 identity 는 filename 기반이다 (§2-8 확정). single-label head 에서 동일
# filename 이 2개 이상 class 폴더에 등장하는 경우는 사용자 라벨링 오류이므로,
# ingest 단계에서 warning + 해당 이미지 전체 skip 처리된다. 과거의 SHA 기반
# content dedup / duplicate_image_policy 옵션은 폐지됐다.


class ClassificationHeadSpec(BaseModel):
    """등록 시점에 사용자가 확정한 head별 계약."""
    name: str = Field(..., min_length=1, max_length=100, description="head 이름")
    multi_label: bool = Field(
        default=False,
        description="True면 한 이미지가 이 head에서 여러 class에 속할 수 있음 (라벨 = list)",
    )
    # classes 순서가 학습 output index 계약(SSOT). 순서를 바꾸면 기존 모델과 호환성이 깨진다.
    classes: list[str] = Field(
        ...,
        min_length=1,
        description="class 이름 순서 있는 리스트. 순서 = 출력 index (절대 바꾸지 말 것)",
    )
    # 각 class 이름이 실제 소스 폴더의 어떤 디렉토리에 대응되는지 절대경로로 지정.
    # 사용자가 편집창에서 class 이름을 변경했을 수 있으므로 폴더명 ≠ class명일 수 있음.
    # 빈 class(이미지 0장)도 정식 class로 허용 — 해당 경로의 이미지는 0장으로 간주.
    source_class_paths: list[str] = Field(
        ...,
        description="classes와 같은 길이. 각 원소는 해당 class 폴더의 절대경로",
    )

    @model_validator(mode="after")
    def check_source_paths_length(self) -> ClassificationHeadSpec:
        if len(self.source_class_paths) != len(self.classes):
            raise ValueError(
                "classes와 source_class_paths 길이가 다릅니다. "
                f"classes={len(self.classes)}, source_class_paths={len(self.source_class_paths)}"
            )
        return self


class DatasetRegisterClassificationRequest(BaseModel):
    """
    Classification RAW 데이터셋 등록 요청.

    폴더 구조 <root>/<head>/<class>/<images>를 스캔·편집한 결과를
    그대로 전달받아, 백엔드가 Celery로 비동기 ingest를 수행한다.

    - 그룹이 신규면 head_schema가 그룹에 새로 기록됨
    - 기존 그룹 재등록이면 head_schema 일관성 검증 후 경고/차단
    """
    group_id: str | None = Field(default=None, description="기존 그룹 ID (새 그룹이면 None)")
    group_name: str | None = Field(default=None, description="새 그룹 생성 시 그룹명")

    modality: str = Field(default="RGB")
    source_origin: str | None = None
    description: str | None = None

    split: ALLOWED_SPLITS = Field(default="NONE", description="TRAIN | VAL | TEST | NONE")

    # 스캔한 데이터셋 루트 절대경로. LOCAL_UPLOAD_BASE 하위여야 함.
    source_root_dir: str = Field(
        ...,
        description="데이터셋 루트 절대경로 (예: /mnt/uploads/hardhat_classification/val)",
    )

    heads: list[ClassificationHeadSpec] = Field(
        ...,
        min_length=1,
        description="등록할 head/class 계약. 순서·이름 모두 사용자 확정 값",
    )

    @model_validator(mode="after")
    def check_group_identifier(self) -> DatasetRegisterClassificationRequest:
        if not self.group_id and not self.group_name:
            raise ValueError("group_id 또는 group_name 중 하나는 필수입니다.")
        return self


class ClassificationHeadWarning(BaseModel):
    """head_schema 일관성 검증 중 발견된 경고(차단은 아님)."""
    head_name: str
    kind: Literal["NEW_HEAD", "NEW_CLASS"]
    detail: str


class DatasetRegisterClassificationResponse(BaseModel):
    """Classification 등록 큐잉 결과."""
    group_id: str
    dataset_id: str
    celery_task_id: str | None = None
    warnings: list[ClassificationHeadWarning] = []


class DatasetUpdate(BaseModel):
    """Dataset 개별 수정 요청 (부분 업데이트)."""
    annotation_format: str | None = None


class DatasetMetaFileReplaceRequest(BaseModel):
    """어노테이션 메타 파일 교체 요청."""
    source_annotation_meta_file: str = Field(
        ...,
        description="교체할 메타 파일 절대경로 (파일 브라우저에서 선택한 경로)",
    )


class DatasetValidateRequest(BaseModel):
    """이미 등록된 데이터셋의 어노테이션 포맷 검증 요청."""
    annotation_format: str = Field(..., description="COCO | YOLO")


class DatasetResponse(DatasetBase):
    """Dataset 응답."""
    id: str
    group_id: str
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    pipeline_execution_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
    pipeline_image_url: str | None = None


class LineageEdgeResponse(BaseModel):
    """Lineage 그래프 엣지 응답."""
    id: str
    source: str
    target: str
    transform_config: dict[str, Any] | None
    pipeline_summary: str | None = None


class LineageGraphResponse(BaseModel):
    """Lineage 전체 그래프 응답."""
    nodes: list[LineageNodeResponse]
    edges: list[LineageEdgeResponse]


# =============================================================================
# 공통 응답
# =============================================================================

# =============================================================================
# 포맷 검증 스키마
# =============================================================================

class FormatValidateRequest(BaseModel):
    """어노테이션 포맷 사전 검증 요청."""
    annotation_format: str = Field(..., description="COCO | YOLO")
    annotation_files: list[str] = Field(
        ...,
        min_length=1,
        description="어노테이션 파일 절대경로 목록",
    )
    annotation_meta_file: str | None = Field(
        default=None,
        description="어노테이션 메타 파일 절대경로 (예: data.yaml). YOLO 클래스 매핑용",
    )


class FormatValidateResponse(BaseModel):
    """어노테이션 포맷 검증 결과."""
    valid: bool = Field(..., description="전체 검증 통과 여부")
    errors: list[str] = Field(default_factory=list, description="검증 실패 메시지 목록")
    summary: dict[str, Any] | None = Field(
        default=None,
        description="검증 성공 시 데이터 요약 (이미지 수, 어노테이션 수, 카테고리 목록 등)",
    )


# =============================================================================
# 공통 응답
# =============================================================================

class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


# =============================================================================
# 데이터셋 뷰어 스키마
# =============================================================================

class SampleAnnotationItem(BaseModel):
    """개별 annotation 정보 (bbox 1개)."""
    category_name: str
    bbox: list[float] | None = None
    area: float | None = None


class SampleImageItem(BaseModel):
    """이미지 1장의 요약 정보 + annotation 목록."""
    image_id: int | str
    file_name: str
    width: int | None = None
    height: int | None = None
    image_url: str
    annotation_count: int
    annotations: list[SampleAnnotationItem] = []


class SampleListResponse(BaseModel):
    """샘플 뷰어용 이미지 목록 응답 (페이지네이션)."""
    items: list[SampleImageItem]
    total: int
    page: int
    page_size: int
    categories: list[str] = []
    bbox_normalized: bool = False
    """bbox가 정규화 좌표(0~1)인 경우 True (YOLO 포맷, 이미지 크기 미로드 시)"""


# =============================================================================
# EDA 통계 스키마
# =============================================================================

class ClassDistributionItem(BaseModel):
    """클래스별 annotation 수 + 이미지 수."""
    category_name: str
    annotation_count: int
    image_count: int


class BboxSizeDistributionItem(BaseModel):
    """bbox 크기 구간별 분포."""
    range_label: str
    count: int


class EdaStatsResponse(BaseModel):
    """EDA 통계 응답."""
    total_images: int
    total_annotations: int
    total_classes: int
    images_without_annotations: int
    class_distribution: list[ClassDistributionItem] = []
    bbox_area_distribution: list[BboxSizeDistributionItem] = []
    image_width_min: int | None = None
    image_width_max: int | None = None
    image_height_min: int | None = None
    image_height_max: int | None = None


# =============================================================================
# Classification 전용 뷰어/EDA 스키마
# =============================================================================
# detection 스키마와 구조 자체가 달라(이미지당 bbox 목록 대신 이미지당 head별
# class 라벨 리스트) 별도 응답 모델로 분리. 라우터는 annotation_format을 보고
# 둘 중 하나를 반환한다(FastAPI response_model은 제거하고 dict로 직렬화).


class ClassificationHeadInfo(BaseModel):
    """샘플 뷰어/EDA에서 공통으로 쓰는 head 요약 (name + multi_label + classes)."""
    name: str
    multi_label: bool
    classes: list[str]


class ClassificationSampleImageItem(BaseModel):
    """Classification 샘플 뷰어용 이미지 1장 정보.

    detection과 달리 bbox/area가 없는 대신 head별 class 라벨을 반환한다.
    `file_name` 은 현재 storage pool 상의 파일명(basename, 표시/링크 기준).
    `original_file_name` 은 merge rename 등으로 원본과 달라졌을 때만 세팅되며,
    동일하면 None 으로 내려간다 — UI 가 이 값을 보고 "(원본: …)" 표시 여부를 결정한다.
    """
    file_name: str
    original_file_name: str | None = None
    image_url: str
    width: int | None = None
    height: int | None = None
    labels: dict[str, list[str]]  # head_name → [class_name, ...]


class ClassificationSampleListResponse(BaseModel):
    """Classification 샘플 뷰어 응답 (페이지네이션)."""
    items: list[ClassificationSampleImageItem]
    total: int
    page: int
    page_size: int
    heads: list[ClassificationHeadInfo] = []


class ClassificationHeadClassDistributionItem(BaseModel):
    """head 내 class별 이미지 수 (positive count 기준)."""
    class_name: str
    image_count: int


class ClassificationHeadDistribution(BaseModel):
    """head 1개의 class 분포.

    single-label head는 class별 image_count 합이 labeled_image_count와 같다.
    multi-label head는 한 이미지가 여러 class에 속할 수 있어 합이 더 클 수 있다.
    """
    head_name: str
    multi_label: bool
    labeled_image_count: int              # 이 head에 라벨이 하나라도 있는 이미지 수
    unlabeled_image_count: int            # 이 head 라벨이 비어있는 이미지 수
    classes: list[ClassificationHeadClassDistributionItem]


class ClassificationCooccurrencePair(BaseModel):
    """head_a × head_b 동시발생 행렬.

    joint_counts[i][j] = classes_a[i] 와 classes_b[j] 를 동시에 갖는 이미지 수.
    marginals a_counts / b_counts 는 각 class의 positive 총 count (정규화용).
    """
    head_a: str
    head_b: str
    classes_a: list[str]
    classes_b: list[str]
    a_counts: list[int]
    b_counts: list[int]
    joint_counts: list[list[int]]


class ClassificationPositiveRatioItem(BaseModel):
    """multi-label head의 class별 positive 비율 (class imbalance 지표)."""
    head_name: str
    class_name: str
    positive_count: int
    negative_count: int
    positive_ratio: float                 # positive / (positive + negative)


class ClassificationEdaResponse(BaseModel):
    """Classification 전용 EDA 응답."""
    total_images: int
    image_width_min: int | None = None
    image_width_max: int | None = None
    image_height_min: int | None = None
    image_height_max: int | None = None
    per_head_distribution: list[ClassificationHeadDistribution] = []
    head_cooccurrence: list[ClassificationCooccurrencePair] = []
    multi_label_positive_ratio: list[ClassificationPositiveRatioItem] = []
