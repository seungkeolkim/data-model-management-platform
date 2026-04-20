"""cls_reorder_classes params_schema UX 라벨 보강

Revision ID: 018_cls_reorder_cls
Revises: 017_cls_sel_black
Create Date: 2026-04-16

배경:
    cls_reorder_classes 구현에 맞춰 params_schema 라벨을 cls_rename_class /
    cls_reorder_heads 와 일관된 표기로 다듬는다.

조치:
    - head_name 라벨: "대상 head 이름" → "대상 Head 이름"
    - ordered_classes 라벨: "새 순서 (…)" → "Class 새 순서 (줄바꿈 구분)"
    - downgrade: 010 시드 당시 라벨로 원복.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "018_cls_reorder_cls"
down_revision: str | None = "017_cls_sel_black"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "cls_reorder_classes"

_NEW_PARAMS: dict = {
    "head_name": {
        "type": "string",
        "label": "대상 Head 이름",
        "required": True,
    },
    "ordered_classes": {
        "type": "textarea",
        "label": "Class 새 순서 (줄바꿈 구분, 기존 class 모두 포함 필수)",
        "required": True,
    },
}

_OLD_PARAMS: dict = {
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
}


def _update(params_schema: dict) -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE manipulators SET params_schema = %s::jsonb WHERE name = %s;",
        (json.dumps(params_schema), _NAME),
    )


def upgrade() -> None:
    _update(_NEW_PARAMS)


def downgrade() -> None:
    _update(_OLD_PARAMS)
