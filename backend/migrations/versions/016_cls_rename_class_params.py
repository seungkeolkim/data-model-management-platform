"""cls_rename_class params_schema UX 라벨 보강

Revision ID: 016_cls_rename_cls_ps
Revises: 015_cls_desc_rewrite
Create Date: 2026-04-16

배경:
    cls_rename_class 는 head_name(string) + mapping(key_value) 두 파라미터
    를 받는다. mapping 을 det_remap_class_name / cls_rename_head 와 동일한
    '+추가' 버튼 UX 로 쓰려면 key_label / value_label 가 필요하고, 라벨
    문구도 classification + cls_manifest 맥락에 맞게 다듬는다.

조치:
    - UPDATE manipulators.params_schema WHERE name = 'cls_rename_class'.
    - downgrade: 010 시드 당시 params_schema 로 원복.
"""
from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op

revision: str = "016_cls_rename_cls_ps"
down_revision: Union[str, None] = "015_cls_desc_rewrite"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 새 params_schema — head_name 라벨은 "대상 Head 이름" 으로 명확화,
# mapping 은 key_value +추가 버튼 UX 전제로 key_label/value_label 명시.
_NEW_PARAMS_SCHEMA: dict = {
    "head_name": {
        "type": "string",
        "label": "대상 Head 이름",
        "required": True,
    },
    "mapping": {
        "type": "key_value",
        "label": "Class 이름 매핑 (원래 → 새 이름)",
        "key_label": "원래 Class 이름",
        "value_label": "새 Class 이름",
        "required": True,
    },
}

# 010 시드 당시 params_schema — downgrade 원복용.
_OLD_PARAMS_SCHEMA: dict = {
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
}


def _update(params_schema: dict) -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE manipulators SET params_schema = %s::jsonb WHERE name = %s;",
        (json.dumps(params_schema), "cls_rename_class"),
    )


def upgrade() -> None:
    _update(_NEW_PARAMS_SCHEMA)


def downgrade() -> None:
    _update(_OLD_PARAMS_SCHEMA)
