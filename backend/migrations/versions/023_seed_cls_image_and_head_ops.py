"""seed cls_crop_image / cls_rotate_image / cls_add_head / cls_set_head_labels_for_all_images

Revision ID: 023_seed_cls_image_and_head_ops
Revises: 022_cls_sample_params_fix
Create Date: 2026-04-20

Classification 이미지 변형 2종 (crop/rotate) 과 head 조작 2종 (add_head /
set_head_labels_for_all_images) 의 DB seed 를 추가한다. Python 구현체는 stub 상태이며
(lib/manipulators/cls_*.py) 팔레트에는 UNIMPLEMENTED 로 노출된다.

설계서 §5 의 "이미지 변형 2종", "Head 추가 노드", "Annotation 일괄 변경 노드"
에 해당. 실구현은 다음 세션에서 진행.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "023_seed_cls_image_and_head_ops"
down_revision: str | None = "022_cls_sample_params_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CREATED_AT = datetime.utcnow().isoformat()


def _build_classification_seed(
    name: str,
    category: str,
    description: str,
    params_schema: dict,
) -> dict:
    """Classification manipulator 용 seed 레코드 (CLS_MANIFEST 고정)."""
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "category": category,
        "scope": json.dumps(["PER_SOURCE", "POST_MERGE"]),
        "compatible_task_types": json.dumps(["CLASSIFICATION"]),
        "compatible_annotation_fmts": json.dumps(["CLS_MANIFEST"]),
        "output_annotation_fmt": "CLS_MANIFEST",
        "params_schema": json.dumps(params_schema),
        "description": description,
        "status": "ACTIVE",
        "version": "1.0.0",
        "created_at": _CREATED_AT,
    }


_SEED_RECORDS = [
    _build_classification_seed(
        name="cls_crop_image",
        category="AUGMENT",
        description="이미지 Crop (상하좌우 비율로 잘라내기)",
        params_schema={
            "top_pct": {
                "type": "number",
                "label": "상단 Crop 비율 (%)",
                "min": 0,
                "max": 50,
                "default": 0,
            },
            "bottom_pct": {
                "type": "number",
                "label": "하단 Crop 비율 (%)",
                "min": 0,
                "max": 50,
                "default": 0,
            },
            "left_pct": {
                "type": "number",
                "label": "좌측 Crop 비율 (%)",
                "min": 0,
                "max": 50,
                "default": 0,
            },
            "right_pct": {
                "type": "number",
                "label": "우측 Crop 비율 (%)",
                "min": 0,
                "max": 50,
                "default": 0,
            },
        },
    ),
    _build_classification_seed(
        name="cls_rotate_image",
        category="AUGMENT",
        description="이미지 회전 (90/180/270도 고정 회전)",
        params_schema={
            "degrees": {
                "type": "select",
                "label": "회전 각도",
                "options": ["90", "180", "270"],
                "default": "180",
                "required": True,
            },
        },
    ),
    _build_classification_seed(
        name="cls_add_head",
        category="CLS_HEAD_CTRL",
        description="신규 Head 추가 (기존 이미지 labels 는 null=unknown)",
        params_schema={
            "head_name": {
                "type": "text",
                "label": "신규 Head 이름",
                "required": True,
            },
            "label_type": {
                "type": "select",
                "label": "라벨 타입",
                "options": ["single", "multi"],
                "default": "single",
                "required": True,
            },
            "class_candidates": {
                "type": "textarea",
                "label": "Class 후보 (줄바꿈 구분, 2개 이상)",
                "required": True,
            },
        },
    ),
    _build_classification_seed(
        name="cls_set_head_labels_for_all_images",
        category="CLS_HEAD_CTRL",
        description="Head Labels 일괄 설정 (특정 head 를 모든 이미지에서 덮어쓰기)",
        params_schema={
            "head_name": {
                "type": "text",
                "label": "대상 Head 이름",
                "required": True,
            },
            "action": {
                "type": "select",
                "label": "일괄 설정 모드",
                "options": ["set_null", "set_classes"],
                "default": "set_null",
                "required": True,
            },
            "classes": {
                "type": "textarea",
                "label": "설정할 Class 이름 (줄바꿈 구분, action=set_classes 일 때만)",
                "required": False,
            },
        },
    ),
]


_SEED_NAMES = tuple(record["name"] for record in _SEED_RECORDS)


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
        _SEED_RECORDS,
    )


def downgrade() -> None:
    quoted_names = ", ".join(f"'{name}'" for name in _SEED_NAMES)
    op.execute(f"DELETE FROM manipulators WHERE name IN ({quoted_names});")
