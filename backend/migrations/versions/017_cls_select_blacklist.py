"""cls_select_heads 를 whitelist → blacklist 방식으로 변경

Revision ID: 017_cls_sel_black
Revises: 016_cls_rename_cls_ps
Create Date: 2026-04-16

배경:
    기존 cls_select_heads 는 유지할 head 를 지정하는 whitelist 방식이었다.
    UX 직관성을 위해 "제거할 head 를 지정" 하는 blacklist 방식으로 전환한다.
    description, params_schema 모두 변경.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "017_cls_sel_black"
down_revision: str | None = "016_cls_rename_cls_ps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "cls_select_heads"

_NEW_DESC = "선택된 Head 제거"
_NEW_PARAMS: dict = {
    "remove_head_names": {
        "type": "textarea",
        "label": "제거할 Head 이름 (줄바꿈 구분)",
        "required": True,
    },
}

_OLD_DESC = "선택된 Head 외 제거"
_OLD_PARAMS: dict = {
    "keep_head_names": {
        "type": "textarea",
        "label": "유지할 head 이름 (줄바꿈 구분)",
        "required": True,
    },
}


def _update(description: str, params_schema: dict) -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE manipulators SET description = %s, params_schema = %s::jsonb WHERE name = %s;",
        (description, json.dumps(params_schema), _NAME),
    )


def upgrade() -> None:
    _update(_NEW_DESC, _NEW_PARAMS)


def downgrade() -> None:
    _update(_OLD_DESC, _OLD_PARAMS)
