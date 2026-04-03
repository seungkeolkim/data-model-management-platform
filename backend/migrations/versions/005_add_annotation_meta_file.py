"""add annotation_meta_file to datasets

Revision ID: 005_add_annotation_meta_file
Revises: 004_add_deleted_at
Create Date: 2026-04-03

datasets 테이블에 annotation_meta_file 컬럼 추가.
YOLO data.yaml 등 어노테이션 메타 파일명을 저장한다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_add_annotation_meta_file"
down_revision: Union[str, None] = "004_add_deleted_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column(
            "annotation_meta_file",
            sa.String(500),
            nullable=True,
            comment="어노테이션 메타 파일명 (예: data.yaml). YOLO 등 클래스 매핑이 별도 파일인 포맷용",
        ),
    )


def downgrade() -> None:
    op.drop_column("datasets", "annotation_meta_file")
