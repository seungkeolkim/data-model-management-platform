"""cls_sample_n_images params_schema type int → number 수정

Revision ID: 022_cls_sample_params_fix
Revises: 021_seed_cls_demote_head
Create Date: 2026-04-17

배경:
    012 seed 에서 params_schema 의 n/seed 필드 type 을 "int" 로 지정했으나,
    DynamicParamForm 이 인식하는 타입은 "number" 이다.
    "int" → "number" 로 갱신하여 폼이 정상 렌더링되도록 한다.
    description 도 현행 015 기준과 맞춘다.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "022_cls_sample_params_fix"
down_revision: str | None = "021_seed_cls_demote_head"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "cls_sample_n_images"

_NEW_PARAMS: dict = {
    "n": {
        "type": "number",
        "label": "샘플 장수",
        "required": True,
        "min": 1,
    },
    "seed": {
        "type": "number",
        "label": "랜덤 시드 (재현성, 기본 42)",
        "required": False,
        "default": 42,
    },
}

_NEW_DESCRIPTION = "N장 랜덤 샘플 추출 (seed 고정으로 재현 가능)"

# downgrade 원복 — 012 seed 당시의 값.
_OLD_PARAMS: dict = {
    "n": {
        "type": "int",
        "label": "샘플 장수",
        "required": True,
    },
    "seed": {
        "type": "int",
        "label": "랜덤 시드 (재현성)",
        "required": False,
    },
}

_OLD_DESCRIPTION = "N장 랜덤 샘플 추출"


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
