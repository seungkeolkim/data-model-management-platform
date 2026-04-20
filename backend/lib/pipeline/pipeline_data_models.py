"""
파이프라인 핵심 데이터 모델.

파이프라인을 흐르는 데이터 구조를 정의.
이미지 파일에는 접근하지 않음 (annotation/label 메타만 처리).

통일포맷 (Detection):
  - 내부에서는 포맷(COCO/YOLO) 구분 없이 category_name(문자열)으로 식별.
  - category_id(정수)는 존재하지 않으며, 디스크 저장 시에만 포맷별 ID를 부여한다.
  - bbox는 항상 COCO absolute [x, y, w, h] 형식. (파이프라인 실행 시 Pillow로 이미지 크기를 읽어 보장)

통일포맷 (Classification):
  - DatasetMeta.head_schema 가 None 이 아니면 classification 데이터셋으로 간주한다.
  - head_schema(list[HeadSchema])가 SSOT — classes 순서가 학습 output index 와 1:1 대응된다.
  - image_record.labels: dict[head_name, list[class_name] | None] — null=unknown, []=explicit empty (§2-12).
  - image_record.file_name 은 manifest.jsonl 의 "filename" 필드와 동일(storage 내 상대경로, "images/{original_filename}" 규약).
  - 이미지 identity = filename. 파일 내용물 기반 식별(SHA 등)은 하지 않으며, 파일명 충돌은 ingest/merge 에서 각자 정책으로 처리한다.

task_kind 는 DatasetMeta.head_schema 의 존재 여부로 판별한다 — executor 는 이 값을 근거로
detection 경로(categories/annotations)와 classification 경로(head_schema/labels) 를 분기한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TaskKind = Literal["DETECTION", "CLASSIFICATION"]


@dataclass
class HeadSchema:
    """
    Classification head 의 클래스 공간 정의.

    attributes:
        name: head 식별자 (예: "hardhat_wear"). manifest.jsonl.labels 의 키와 일치한다.
        multi_label: 한 이미지가 해당 head 내 여러 class 를 동시에 가질 수 있는지 여부.
        classes: class 이름 배열. 이 순서가 학습 모델 output index 의 SSOT 이며,
                 merge/reorder 규칙은 이 순서를 절대 불변으로 취급한다.
                 (예외: cls_reorder_classes manipulator 로 명시적 reorder 시에만 변경)
    """
    name: str
    multi_label: bool
    classes: list[str]


@dataclass
class Annotation:
    """
    포맷 독립적 내부 Annotation 표현.
    COCO/YOLO 등 모든 포맷을 이 구조로 변환하여 처리.
    category_name으로 클래스를 식별하며, 정수 ID는 저장 시점에만 부여된다.
    """
    annotation_type: str  # BBOX | SEGMENTATION | LABEL | ATTRIBUTE
    category_name: str    # 클래스 이름 (예: "person", "car")
    bbox: list[float] | None = None          # [x, y, w, h] COCO absolute 형식
    segmentation: list[list[float]] | None = None
    label: str | None = None
    attributes: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # 포맷별 추가 필드


@dataclass
class ImageRecord:
    """
    이미지 1장에 대한 메타 정보.

    Detection 경로:
        file_name      — 원본 파일명 (예: "000123.jpg")
        annotations    — bbox/segmentation/label Annotation 리스트
        labels         — 사용하지 않음 (None)

    Classification 경로:
        file_name      — "images/{original_filename}" 규약 (storage 내 상대경로). 파일명이
                         이미지 identity 이며, 이름이 같은 파일은 같은 이미지로 간주된다.
                         이미지 변형 manipulator(rotate/crop 등)는 postfix 로 새 파일명을 부여한다
                         (예: "truck_001.jpg" → "truck_001_rotated_180.jpg").
        labels         — {head_name: list[class_name] | None}.
                         null=unknown (학습 제외), []=explicit empty (전부 neg). §2-12 확정 규약.
                         single-label head: null 또는 [class 1개]만 허용.
        annotations    — 비움 (detection 전용)
    """
    image_id: int | str
    file_name: str
    width: int | None = None
    height: int | None = None
    annotations: list[Annotation] = field(default_factory=list)
    # ── Classification 전용 ──
    labels: dict[str, list[str] | None] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetMeta:
    """
    하나의 데이터셋(split+version)에 대한 메타데이터.
    annotation/label 처리 단계에서 이 구조를 변환하여 최종 결과를 만듦.

    통일포맷:
      - annotation_format 필드 없음. 포맷은 로드/저장 시점에서만 의미를 가짐.
      - task 종류(detection/classification)는 head_schema 유무로 판별한다(task_kind).

    Detection 경로:
        categories     — 클래스 이름 목록 (list[str]). 정수 ID 없음.
        head_schema    — None

    Classification 경로:
        head_schema    — HeadSchema 배열. 이 순서가 head 출력 index 의 SSOT.
        categories     — 비움([]) — 사용하지 않음
    """
    dataset_id: str                  # Dataset.id (DB)
    storage_uri: str                 # NAS 상대경로
    categories: list[str] = field(default_factory=list)
    image_records: list[ImageRecord] = field(default_factory=list)
    # ── Classification 전용 ──
    head_schema: list[HeadSchema] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def image_count(self) -> int:
        return len(self.image_records)

    @property
    def task_kind(self) -> TaskKind:
        """head_schema 유무로 task 종류를 판별. executor 의 주요 분기 기준."""
        return "CLASSIFICATION" if self.head_schema is not None else "DETECTION"


@dataclass
class ImageManipulationSpec:
    """
    이미지 1장에 적용할 변환 명세.
    Annotation 처리 단계에서 결정되며, 실제 이미지 I/O는 ImageMaterializer가 수행.
    """
    operation: str           # "rotate_image" | "mask_region" 등
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImagePlan:
    """
    이미지 1장의 처리 계획.
    Annotation phase 완료 후 ImageMaterializer에 전달.
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
    Annotation phase → ImagePlan 확정 → ImageMaterializer 실행 순서로 사용.
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
