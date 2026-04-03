"""
Pipeline 핵심 데이터 모델 (Phase 2에서 구현)

파이프라인을 흐르는 데이터 구조를 정의.
이미지 파일에는 접근하지 않음 (annotation만 처리).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Annotation:
    """
    포맷 독립적 내부 Annotation 표현.
    COCO/YOLO/ATTR_JSON 등 모든 포맷을 이 구조로 변환하여 처리.
    """
    annotation_type: str  # BBOX | SEGMENTATION | LABEL | ATTRIBUTE
    category_id: int
    bbox: list[float] | None = None          # [x, y, w, h] COCO 형식
    segmentation: list[list[float]] | None = None
    label: str | None = None
    attributes: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # 포맷별 추가 필드


@dataclass
class ImageRecord:
    """이미지 1장의 annotation 정보."""
    image_id: int | str
    file_name: str           # 원본 파일명
    width: int | None = None
    height: int | None = None
    annotations: list[Annotation] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetMeta:
    """
    하나의 데이터셋(split+version)에 대한 메타데이터.
    annotation 처리 단계에서 이 구조를 변환하여 최종 결과를 만듦.
    """
    dataset_id: str                  # Dataset.id (DB)
    storage_uri: str                 # NAS 상대경로
    annotation_format: str           # COCO | YOLO | ...
    categories: list[dict] = field(default_factory=list)  # [{id, name, supercategory}]
    image_records: list[ImageRecord] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def image_count(self) -> int:
        return len(self.image_records)

    @property
    def category_names(self) -> list[str]:
        return [c["name"] for c in self.categories]


@dataclass
class ImageManipulationSpec:
    """
    이미지 1장에 적용할 변환 명세.
    Annotation 처리 단계에서 결정되며, 실제 이미지 I/O는 ImageExecutor가 수행.
    """
    operation: str           # "rotate_180" | "change_compression" | "mask_region" 등
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImagePlan:
    """
    이미지 1장의 처리 계획.
    Annotation phase 완료 후 ImageExecutor에 전달.
    """
    src_uri: str             # 원본 이미지 상대경로
    dst_uri: str             # 출력 이미지 상대경로
    specs: list[ImageManipulationSpec] = field(default_factory=list)

    @property
    def is_copy_only(self) -> bool:
        """변환 없이 단순 복사인지 여부."""
        return len(self.specs) == 0


@dataclass
class DatasetPlan:
    """
    파이프라인 실행 전체 계획.
    Annotation phase → ImagePlan 확정 → ImageExecutor 실행 순서로 사용.
    """
    output_meta: DatasetMeta
    image_plans: list[ImagePlan] = field(default_factory=list)

    @property
    def total_images(self) -> int:
        return len(self.image_plans)

    @property
    def copy_only_count(self) -> int:
        return sum(1 for p in self.image_plans if p.is_copy_only)

    @property
    def transform_count(self) -> int:
        return self.total_images - self.copy_only_count
