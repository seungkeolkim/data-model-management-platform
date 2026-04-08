"""seed manipulators - initial data

Revision ID: 002_seed_manipulators
Revises: 001_initial
Create Date: 2026-02-19

사전 등록 Manipulator 전체 목록 시드 데이터.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_seed_manipulators"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_CREATED_AT = datetime.utcnow().isoformat()


def _build_manipulator_seed_record(
    name,
    category,
    scope,
    task_types,
    annotation_fmts,
    output_fmt=None,
    params_schema=None,
    description="",
    status="ACTIVE",
):
    """
    Manipulator 시드 데이터 딕셔너리를 생성하여 반환한다.

    psycopg2는 Python dict/list를 JSONB 컬럼에 자동 직렬화하지 않으므로,
    scope, task_types, annotation_fmts, params_schema는 json.dumps()로 변환 후 삽입해야 한다.
    bulk_insert 시 이 함수를 호출해 MANIPULATORS 리스트를 구성한다.
    """
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "category": category,
        "scope": json.dumps(scope),
        "compatible_task_types": json.dumps(task_types) if task_types is not None else None,
        "compatible_annotation_fmts": json.dumps(annotation_fmts) if annotation_fmts is not None else None,
        "output_annotation_fmt": output_fmt,
        "params_schema": json.dumps(params_schema or {}),
        "description": description,
        "status": status,
        "version": "1.0.0",
        "created_at": _SEED_CREATED_AT,
    }


MANIPULATORS = [
    # =========================================================================
    # ANNOTATION_FILTER — Annotation 필터 (이미지는 유지, annotation만 제거)
    # =========================================================================
    _build_manipulator_seed_record(
        name="filter_remain_selected_class_names_only_in_annotation",
        category="ANNOTATION_FILTER",
        scope=["PER_SOURCE", "POST_MERGE"],
        task_types=["DETECTION", "SEGMENTATION"],
        annotation_fmts=["COCO", "YOLO"],
        description="Annotation에 지정 class만 남기기 (나머지 class는 annotation에서만 제거)",
        params_schema={
            "keep_class_names": {
                "type": "textarea",
                "label": "남길 class 이름 (줄바꿈 구분)",
                "required": True,
            },
        },
    ),
    
    # =========================================================================
    # IMAGE_FILTER — Image 필터 (이미지 자체를 유지/제거)
    # =========================================================================
    _build_manipulator_seed_record(
        name="filter_keep_images_containing_class_name",
        category="IMAGE_FILTER",
        scope=["PER_SOURCE", "POST_MERGE"],
        task_types=["DETECTION", "SEGMENTATION", "ATTR_CLASSIFICATION"],
        annotation_fmts=["COCO", "YOLO"],
        description="지정 class 포함 이미지만 유지 (지정 class가 1개도 없는 이미지 제거)",
        params_schema={
            "class_names": {
                "type": "textarea",
                "label": "유지할 클래스 이름 (줄바꿈 구분)",
                "required": True,
            },
        },
    ),
    _build_manipulator_seed_record(
        name="filter_remove_images_containing_class_name",
        category="IMAGE_FILTER",
        scope=["PER_SOURCE", "POST_MERGE"],
        task_types=["DETECTION", "SEGMENTATION", "ATTR_CLASSIFICATION"],
        annotation_fmts=["COCO", "YOLO"],
        description="지정 class 포함 이미지 제거 (class중 1개라도 포함한 이미지 제거)",
        params_schema={
            "class_names": {
                "type": "textarea",
                "label": "제거할 클래스 이름 (줄바꿈 구분)",
                "required": True,
            },
        },
    ),

    # =========================================================================
    # PER_SOURCE - REMAP
    # =========================================================================
    _build_manipulator_seed_record(
        name="remap_class_name",
        category="REMAP",
        scope=["PER_SOURCE", "POST_MERGE"],
        task_types=["DETECTION", "SEGMENTATION", "ATTR_CLASSIFICATION"],
        annotation_fmts=["COCO", "YOLO"],
        description="category_id 기준으로 class name 변경 (rename 매핑)",
        params_schema={
            "mapping": {
                "type": "key_value",
                "label": "원래 이름 → 새 이름 매핑",
                "key_label": "원래 클래스 이름",
                "value_label": "새 클래스 이름",
                "required": True,
            },
        },
    ),

    # =========================================================================
    # PER_SOURCE - AUGMENT
    # =========================================================================
    _build_manipulator_seed_record(
        name="rotate_180",
        category="AUGMENT",
        scope=["PER_SOURCE"],
        task_types=["DETECTION", "SEGMENTATION"],
        annotation_fmts=["COCO", "YOLO"],
        description="이미지 180도 회전 (annotation bbox/seg 좌표 자동 변환)",
        params_schema={},  # 파라미터 없음
    ),
    _build_manipulator_seed_record(
        name="change_compression",
        category="AUGMENT",
        scope=["PER_SOURCE"],
        task_types=None,  # 포맷 무관
        annotation_fmts=None,
        description="JPEG quality 조정 (annotation 변환 없음, 이미지만 변경)",
        params_schema={
            "quality": {
                "type": "slider",
                "label": "JPEG quality",
                "min": 10,
                "max": 100,
                "default": 80,
                "required": True,
            },
            "output_format": {
                "type": "select",
                "label": "출력 포맷",
                "options": ["jpg", "png"],
                "default": "jpg",
            },
        },
    ),
    _build_manipulator_seed_record(
        name="mask_region_by_class",
        category="AUGMENT",
        scope=["PER_SOURCE"],
        task_types=["DETECTION", "SEGMENTATION"],
        annotation_fmts=["COCO"],
        description="특정 class의 bbox/segmentation 영역을 이미지에서 masking (검게 칠하기)",
        params_schema={
            "class_names": {
                "type": "multiselect",
                "label": "masking할 클래스 이름 목록",
                "required": True,
            },
            "fill_color": {
                "type": "color",
                "label": "fill 색상 (기본: 검정)",
                "default": "#000000",
            },
        },
        status="EXPERIMENTAL",
    ),

    # =========================================================================
    # PER_SOURCE - FORMAT_CONVERT
    # =========================================================================
    _build_manipulator_seed_record(
        name="format_convert_to_yolo",
        category="FORMAT_CONVERT",
        scope=["PER_SOURCE"],
        task_types=["DETECTION"],
        annotation_fmts=["COCO"],
        output_fmt="YOLO",
        description="COCO → YOLO 포맷 변환",
        params_schema={},
    ),
    _build_manipulator_seed_record(
        name="format_convert_to_coco",
        category="FORMAT_CONVERT",
        scope=["PER_SOURCE"],
        task_types=["DETECTION"],
        annotation_fmts=["YOLO"],
        output_fmt="COCO",
        description="YOLO → COCO 포맷 변환",
        params_schema={},
    ),
    _build_manipulator_seed_record(
        name="format_convert_visdrone_to_coco",
        category="FORMAT_CONVERT",
        scope=["PER_SOURCE"],
        task_types=["DETECTION"],
        annotation_fmts=["CUSTOM"],
        output_fmt="COCO",
        description="VisDrone txt 포맷 → COCO 변환",
        params_schema={},
    ),
    _build_manipulator_seed_record(
        name="format_convert_visdrone_to_yolo",
        category="FORMAT_CONVERT",
        scope=["PER_SOURCE"],
        task_types=["DETECTION"],
        annotation_fmts=["CUSTOM"],
        output_fmt="YOLO",
        description="VisDrone txt 포맷 → YOLO 변환",
        params_schema={},
    ),

    # =========================================================================
    # PER_SOURCE & POST_MERGE - SAMPLE
    # =========================================================================
    _build_manipulator_seed_record(
        name="sample_n_images",
        category="SAMPLE",
        scope=["PER_SOURCE", "POST_MERGE"],
        task_types=None,
        annotation_fmts=None,
        description="N장 랜덤 샘플 추출 (테스트 또는 빠른 검증용)",
        params_schema={
            "n": {
                "type": "number",
                "label": "샘플 수",
                "min": 1,
                "required": True,
            },
            "seed": {
                "type": "number",
                "label": "랜덤 시드 (재현성, 선택)",
                "default": 42,
            },
        },
    ),

    # =========================================================================
    # POST_MERGE - MERGE / SHUFFLE
    # =========================================================================
    _build_manipulator_seed_record(
        name="merge_datasets",
        category="MERGE",
        scope=["POST_MERGE"],
        task_types=None,
        annotation_fmts=None,
        description="복수 소스 데이터셋 병합, 이미지명 중복 자동 해결 (prefix 추가)",
        params_schema={
            "duplicate_strategy": {
                "type": "select",
                "label": "이미지명 중복 처리",
                "options": ["prefix_source_name", "prefix_index"],
                "default": "prefix_source_name",
            },
        },
    ),
    _build_manipulator_seed_record(
        name="shuffle_image_ids",
        category="SAMPLE",
        scope=["POST_MERGE"],
        task_types=None,
        annotation_fmts=None,
        description="이미지 id 셔플 (병합 후 id 순서 랜덤화)",
        params_schema={
            "seed": {
                "type": "number",
                "label": "랜덤 시드",
                "default": 42,
            },
        },
    ),
]


def upgrade() -> None:
    op.bulk_insert(
        sa.table(
            "manipulators",
            sa.column("id"),
            sa.column("name"),
            sa.column("category"),
            sa.column("scope"),
            sa.column("compatible_task_types"),
            sa.column("compatible_annotation_fmts"),
            sa.column("output_annotation_fmt"),
            sa.column("params_schema"),
            sa.column("description"),
            sa.column("status"),
            sa.column("version"),
            sa.column("created_at"),
        ),
        MANIPULATORS,
    )


def downgrade() -> None:
    op.execute("DELETE FROM manipulators;")
