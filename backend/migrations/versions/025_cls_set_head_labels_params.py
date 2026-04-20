"""cls_set_head_labels_for_all_images params_schema 실구현 기준 갱신

Revision ID: 025_cls_set_head_labels_params
Revises: 024_cls_add_head_params
Create Date: 2026-04-20

배경:
    `cls_set_head_labels_for_all_images` 실구현 시 입력 UX 를 단순화함:
      - `action: select("set_null"|"set_classes")` → `set_unknown: checkbox (bool)` 로 변경.
        체크 = 모든 이미지의 해당 head 를 null(unknown) 으로 교체.
        미체크 = classes 에 입력한 이름으로 교체.
      - 순서: head_name → set_unknown → classes.

    실구현은 single-label head 에 다수 class 가 들어오면 ValueError 로 차단하고,
    head_schema.classes 바깥 이름도 거부한다 (§2-4 SSOT / §2-12 null/[] 규약).
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "025_cls_set_head_labels_params"
down_revision: str | None = "024_cls_add_head_params"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "cls_set_head_labels_for_all_images"

# 실구현 기준 — head_name → set_unknown → classes 순서.
_NEW_PARAMS: dict = {
    "head_name": {
        "type": "text",
        "label": "대상 Head 이름",
        "required": True,
    },
    "set_unknown": {
        "type": "checkbox",
        "label": "Unknown 으로 초기화 (체크 시 classes 무시하고 모든 라벨을 null 로)",
        "default": False,
        "required": False,
    },
    "classes": {
        "type": "textarea",
        "label": (
            "설정할 Class 이름 (줄바꿈 구분, set_unknown 미체크 시 사용). "
            "single-label 은 정확히 1개, multi-label 은 0개 이상(빈 값 허용)."
        ),
        "required": False,
    },
}

_NEW_DESCRIPTION = (
    "Head Labels 일괄 설정 (특정 head 를 모든 이미지에서 동일 값으로 overwrite — "
    "unknown 또는 지정 class 조합)"
)

# 023 seed 당시의 값 (downgrade 원복용).
_OLD_PARAMS: dict = {
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
}

_OLD_DESCRIPTION = "Head Labels 일괄 설정 (특정 head 를 모든 이미지에서 덮어쓰기)"


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
