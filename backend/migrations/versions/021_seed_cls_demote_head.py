"""seed cls_demote_head_to_single_label manipulator

Revision ID: 021_seed_cls_demote_head
Revises: 020_cls_merge_classes_params
Create Date: 2026-04-17

Multi-label head 를 Single-label 로 강등하는 manipulator 를 manipulators 테이블에 추가한다.
cls_merge_classes 로 class 를 줄인 뒤 multi→single 전환에 사용.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "021_seed_cls_demote_head"
down_revision: str | None = "020_cls_merge_classes_params"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "cls_demote_head_to_single_label"

_SEED_RECORD = {
    "id": str(uuid.uuid4()),
    "name": _NAME,
    "category": "CLS_HEAD_CTRL",
    "scope": json.dumps(["PER_SOURCE", "POST_MERGE"]),
    "compatible_task_types": json.dumps(["CLASSIFICATION"]),
    "compatible_annotation_fmts": json.dumps(["CLS_MANIFEST"]),
    "output_annotation_fmt": "CLS_MANIFEST",
    "params_schema": json.dumps({
        "head_name": {
            "type": "text",
            "label": "강등 대상 Head 이름",
            "required": True,
        },
        "on_violation": {
            "type": "select",
            "label": "Single-label 위반 이미지 처리",
            "options": ["fail", "skip"],
            "default": "fail",
            "required": True,
        },
    }),
    "description": "Multi→Single 강등 (multi-label head 를 single-label 로 변환)",
    "status": "ACTIVE",
    "version": "1.0.0",
    "created_at": datetime.utcnow().isoformat(),
}


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
        [_SEED_RECORD],
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM manipulators WHERE name = '{_NAME}';")
