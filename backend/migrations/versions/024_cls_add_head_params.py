"""cls_add_head params_schema 실구현 기준 갱신

Revision ID: 024_cls_add_head_params
Revises: 023_seed_cls_image_and_head_ops
Create Date: 2026-04-20

배경:
    `cls_add_head` 실구현 시 입력 UX 를 확정함:
      - `label_type: select("single"|"multi")` → `multi_label: checkbox (bool)` 로 변경
        (체크 = multi-label head, 미체크 = single-label head)
      - 순서 조정: head_name → multi_label → class_candidates
    실구현은 신규 head 를 head_schema 말단에 추가하고, 모든 이미지의 신규 head labels 를
    `null` (unknown, §2-12) 로 채운다.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "024_cls_add_head_params"
down_revision: str | None = "023_seed_cls_image_and_head_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "cls_add_head"

# 실구현 기준 — head_name → multi_label → class_candidates 순서.
_NEW_PARAMS: dict = {
    "head_name": {
        "type": "text",
        "label": "신규 Head 이름",
        "required": True,
    },
    "multi_label": {
        "type": "checkbox",
        "label": "Multi-label 여부 (체크 시 한 이미지가 여러 class 를 동시에 가질 수 있음)",
        "default": False,
        "required": False,
    },
    "class_candidates": {
        "type": "textarea",
        "label": "Class 후보 (줄바꿈 구분, 2개 이상, 순서 = 학습 output index)",
        "required": True,
    },
}

_NEW_DESCRIPTION = (
    "신규 Head 추가 (기존 이미지 labels 는 null=unknown, 신규 head 는 맨 뒤에 추가)"
)

# 023 seed 당시의 값 (downgrade 원복용).
_OLD_PARAMS: dict = {
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
}

_OLD_DESCRIPTION = "신규 Head 추가 (기존 이미지 labels 는 null=unknown)"


def _update(params_schema: dict, description: str) -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE manipulators "
        "SET params_schema = %s::jsonb, description = %s "
        "WHERE name = %s;",
        (json.dumps(params_schema), description, _NAME),
    )


def upgrade() -> None:
    _update(_NEW_PARAMS, _NEW_DESCRIPTION)


def downgrade() -> None:
    _update(_OLD_PARAMS, _OLD_DESCRIPTION)
