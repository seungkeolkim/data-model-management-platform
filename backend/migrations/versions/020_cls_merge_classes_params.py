"""cls_merge_classes params_schema 실구현 기준 갱신

Revision ID: 020_cls_merge_classes_params
Revises: 019_cls_merge_params
Create Date: 2026-04-17

배경:
    `cls_merge_classes` 실구현에서 파라미터 이름이 변경됨:
      - `merged_into` → `target_class` (더 명확한 이름)
    params_schema 를 실구현 기준으로 교체하고 description 도 갱신한다.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "020_cls_merge_classes_params"
down_revision: str | None = "019_cls_merge_params"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "cls_merge_classes"

_NEW_PARAMS: dict = {
    "head_name": {
        "type": "text",
        "label": "대상 Head 이름",
        "required": True,
    },
    "source_classes": {
        "type": "textarea",
        "label": "병합 대상 Class 이름 (줄바꿈 구분, 2개 이상)",
        "required": True,
    },
    "target_class": {
        "type": "text",
        "label": "병합 후 Class 이름",
        "required": True,
    },
}

_NEW_DESCRIPTION = "Head 내 Class 병합 (여러 class → 하나로 통합)"

# downgrade 원복 — 010 seed 당시의 값.
_OLD_PARAMS: dict = {
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
}

_OLD_DESCRIPTION = (
    "같은 head 내 여러 class 를 하나로 병합. labels 에서 해당 class 들을 "
    "target 으로 치환 후 dedup."
)


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
