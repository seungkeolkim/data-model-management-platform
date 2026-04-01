"""add annotation_files to datasets

Revision ID: 003_add_annotation_files
Revises: 002_seed_manipulators
Create Date: 2026-03-31

datasets 테이블에 annotation_files JSONB 컬럼 추가.
RAW 등록 플로우 변경으로 어노테이션 파일 목록을 DB에서 추적하기 위함.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_add_annotation_files"
down_revision: Union[str, None] = "002_seed_manipulators"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column(
            "annotation_files",
            postgresql.JSONB,
            nullable=True,
            comment='어노테이션 파일명 목록. 예: ["instances_train.json", "captions.json"]. NULL이면 레거시 annotation.json 컨벤션',
        ),
    )


def downgrade() -> None:
    op.drop_column("datasets", "annotation_files")
