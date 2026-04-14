"""add head_schema JSONB to dataset_groups

Revision ID: 009_add_head_schema
Revises: 008_merge_attr_classification
Create Date: 2026-04-14

Classification 등록을 위해 DatasetGroup에 head_schema JSONB 컬럼을 추가한다.
이 컬럼은 그룹 단위의 head/class 계약(SSOT) 을 저장한다.

예시:
    {"heads": [
        {"name": "hardhat_wear", "multi_label": false,
         "classes": ["no_helmet", "helmet"]},
        {"name": "visibility",   "multi_label": false,
         "classes": ["unseen", "seen"]}
    ]}

- classification(task_types에 CLASSIFICATION 포함) 그룹만 값을 채움
- detection 등 다른 task 그룹에서는 NULL 유지
- 샘플 단위 라벨은 DB에 저장하지 않고 manifest.jsonl 파일에만 보관한다
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "009_add_head_schema"
down_revision: Union[str, None] = "008_merge_attr_classification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dataset_groups",
        sa.Column(
            "head_schema",
            JSONB,
            nullable=True,
            comment=(
                "Classification 전용. head별 name/multi_label/classes 순서. "
                "학습 output index의 SSOT"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("dataset_groups", "head_schema")
