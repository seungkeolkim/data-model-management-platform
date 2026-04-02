"""add deleted_at for soft delete

Revision ID: 004_add_deleted_at
Revises: 003_add_annotation_files
Create Date: 2026-04-02

dataset_groups, datasets 테이블에 deleted_at 컬럼 추가.
소프트 삭제 구현: NULL이면 활성 상태, 값이 있으면 삭제된 상태.
삭제된 레코드도 버전 이력 조회에 포함되어 다음 버전 자동 계산이 정확하게 동작한다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_add_deleted_at"
down_revision: Union[str, None] = "003_add_annotation_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dataset_groups",
        sa.Column(
            "deleted_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            comment="소프트 삭제 시각. NULL이면 활성 상태",
        ),
    )
    op.add_column(
        "datasets",
        sa.Column(
            "deleted_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            comment="소프트 삭제 시각. NULL이면 활성 상태",
        ),
    )


def downgrade() -> None:
    op.drop_column("datasets", "deleted_at")
    op.drop_column("dataset_groups", "deleted_at")
