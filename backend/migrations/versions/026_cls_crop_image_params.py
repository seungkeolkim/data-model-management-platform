"""cls_crop_image params_schema 실구현 기준 갱신

Revision ID: 026_cls_crop_image_params
Revises: 025_cls_set_head_labels_params
Create Date: 2026-04-20

배경:
    `cls_crop_image` 실구현 시 입력 UX 를 단순화함. 최초 seed(023) 는 상하좌우 4방향
    각각의 비율을 받는 4-필드 구조였으나, 실제 요구는 "수직축 한쪽 영역만 잘라내기"
    이므로 다음 2-필드 구조로 축소함:

      - direction: select("상단"|"하단"), default "상단"
      - crop_pct:  number (1~99, step=1), default 30

    이미지 상단(=위쪽) 또는 하단(=아래쪽) 로부터 전체 height 의 crop_pct%% 를 잘라낸다.
    width 는 변하지 않으며, 결과 height = 원본 height * (100 - crop_pct) / 100.

    수정 파일명 postfix 규약 (§6-1 filename-identity):
        direction="상단" + crop_pct=30 → "_crop_up_030"
        direction="하단" + crop_pct=30 → "_crop_down_030"
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "026_cls_crop_image_params"
down_revision: str | None = "025_cls_set_head_labels_params"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "cls_crop_image"

# 실구현 기준 — 상/하 중 한쪽에서 비율을 잘라냄.
_NEW_PARAMS: dict = {
    "direction": {
        "type": "select",
        "label": "Crop 방향 (상단 / 하단)",
        "options": ["상단", "하단"],
        "default": "상단",
        "required": True,
    },
    "crop_pct": {
        "type": "number",
        "label": "Crop 비율 (%) — 전체 height 중 잘라낼 비율",
        "min": 1,
        "max": 99,
        "default": 30,
        "required": True,
    },
}

_NEW_DESCRIPTION = "이미지 Crop (상단 또는 하단 영역을 지정 비율(%)만큼 잘라내기)"

# 023 seed 당시의 값 (downgrade 원복용).
_OLD_PARAMS: dict = {
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
}

_OLD_DESCRIPTION = "이미지 Crop (상하좌우 비율로 잘라내기)"


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
