"""seed classification manipulators (stubs)

Revision ID: 010_seed_cls_manips
Revises: 009_add_head_schema
Create Date: 2026-04-15

Classification 전용 manipulator 8종 seed.
실제 transform 로직은 stub 상태이며, 본 seed 는 팔레트 노출과
node-to-node IO 연결성을 먼저 검증하기 위한 것이다.

대상 manipulator (lib/manipulators/ 아래 UnitManipulator 서브클래스와 1:1 매칭):
  - select_classification_heads
  - rename_classification_head
  - reorder_classification_heads
  - rename_classification_class
  - merge_classification_classes
  - reorder_classification_classes
  - filter_by_classification_class
  - remove_images_without_classification_label
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_seed_cls_manips"
down_revision: Union[str, None] = "009_add_head_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SEED_CREATED_AT = datetime.utcnow().isoformat()


def _build_cls_seed(
    name: str,
    category: str,
    scope: list[str],
    params_schema: dict,
    description: str,
) -> dict:
    """Classification manipulator 용 seed 레코드. 모두 CLS_MANIFEST + CLASSIFICATION 으로 고정."""
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "category": category,
        "scope": json.dumps(scope),
        "compatible_task_types": json.dumps(["CLASSIFICATION"]),
        "compatible_annotation_fmts": json.dumps(["CLS_MANIFEST"]),
        "output_annotation_fmt": "CLS_MANIFEST",
        "params_schema": json.dumps(params_schema),
        "description": description,
        "status": "ACTIVE",
        "version": "1.0.0",
        "created_at": _SEED_CREATED_AT,
    }


CLASSIFICATION_MANIPULATORS = [
    _build_cls_seed(
        name="select_classification_heads",
        category="SCHEMA",
        scope=["PER_SOURCE", "POST_MERGE"],
        description="Head 선택 — 지정한 head 만 유지하고 나머지는 head_schema/labels 에서 제거한다.",
        params_schema={
            "keep_head_names": {
                "type": "textarea",
                "label": "유지할 head 이름 (줄바꿈 구분)",
                "required": True,
            },
        },
    ),
    _build_cls_seed(
        name="rename_classification_head",
        category="SCHEMA",
        scope=["PER_SOURCE", "POST_MERGE"],
        description="Head 이름 변경 — head_schema[*].name 과 labels 키를 함께 rename. 주로 merge 전 충돌 회피 용도.",
        params_schema={
            "mapping": {
                "type": "key_value",
                "label": "원래 head 이름 → 새 head 이름",
                "required": True,
            },
        },
    ),
    _build_cls_seed(
        name="reorder_classification_heads",
        category="SCHEMA",
        scope=["PER_SOURCE", "POST_MERGE"],
        description="Head 순서 변경 — head_schema 배열을 지정한 순서로 재정렬. merge 전 순서 통일 용도.",
        params_schema={
            "ordered_head_names": {
                "type": "textarea",
                "label": "새 순서 (줄바꿈 구분, 모든 head 포함 필수)",
                "required": True,
            },
        },
    ),
    _build_cls_seed(
        name="rename_classification_class",
        category="REMAP",
        scope=["PER_SOURCE", "POST_MERGE"],
        description="특정 head 내 class 이름 변경 — classes 배열과 labels 값도 함께 rename.",
        params_schema={
            "head_name": {
                "type": "string",
                "label": "대상 head 이름",
                "required": True,
            },
            "mapping": {
                "type": "key_value",
                "label": "원래 class 이름 → 새 class 이름",
                "required": True,
            },
        },
    ),
    _build_cls_seed(
        name="merge_classification_classes",
        category="REMAP",
        scope=["PER_SOURCE", "POST_MERGE"],
        description="같은 head 내 여러 class 를 하나로 병합. labels 에서 해당 class 들을 target 으로 치환 후 dedup.",
        params_schema={
            "head_name": {
                "type": "string",
                "label": "대상 head 이름",
                "required": True,
            },
            "source_classes": {
                "type": "textarea",
                "label": "병합 대상 class 이름 (줄바꿈 구분)",
                "required": True,
            },
            "merged_into": {
                "type": "string",
                "label": "병합 후 class 이름",
                "required": True,
            },
        },
    ),
    _build_cls_seed(
        name="reorder_classification_classes",
        category="SCHEMA",
        scope=["PER_SOURCE", "POST_MERGE"],
        description=(
            "특정 head 의 class 순서 변경 — classes 배열을 재정렬. "
            "classes 순서는 학습 output index SSOT 이므로 신중히 사용."
        ),
        params_schema={
            "head_name": {
                "type": "string",
                "label": "대상 head 이름",
                "required": True,
            },
            "ordered_classes": {
                "type": "textarea",
                "label": "새 순서 (줄바꿈 구분, 기존 classes 모두 포함 필수)",
                "required": True,
            },
        },
    ),
    _build_cls_seed(
        name="filter_by_classification_class",
        category="IMAGE_FILTER",
        scope=["PER_SOURCE", "POST_MERGE"],
        description="특정 head 의 특정 class 를 포함(include)하거나 제외(exclude) 하는 이미지 단위 필터.",
        params_schema={
            "head_name": {
                "type": "string",
                "label": "대상 head 이름",
                "required": True,
            },
            "class_names": {
                "type": "textarea",
                "label": "대상 class 이름 (줄바꿈 구분)",
                "required": True,
            },
            "mode": {
                "type": "enum",
                "label": "모드",
                "options": ["include", "exclude"],
                "default": "include",
                "required": True,
            },
        },
    ),
    _build_cls_seed(
        name="remove_images_without_classification_label",
        category="IMAGE_FILTER",
        scope=["PER_SOURCE", "POST_MERGE"],
        description="지정한 head(비우면 전체) 에 label 이 없는 이미지를 제거. multi_label head 의 라벨 누락 정리 용도.",
        params_schema={
            "target_head_names": {
                "type": "textarea",
                "label": "대상 head 이름 (줄바꿈 구분, 비우면 전체 head)",
                "required": False,
            },
        },
    ),
]


def upgrade() -> None:
    """Classification manipulator 8종을 manipulators 테이블에 INSERT."""
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
        CLASSIFICATION_MANIPULATORS,
    )


def downgrade() -> None:
    """Classification manipulator 8종만 name 기준으로 삭제 (detection seed 는 보존)."""
    names_sql = ", ".join(
        f"'{entry['name']}'" for entry in CLASSIFICATION_MANIPULATORS
    )
    op.execute(f"DELETE FROM manipulators WHERE name IN ({names_sql});")
