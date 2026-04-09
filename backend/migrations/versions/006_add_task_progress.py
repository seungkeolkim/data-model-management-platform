"""add task_progress JSONB to pipeline_executions

Revision ID: 006_add_task_progress
Revises: 005_add_annotation_meta_file
Create Date: 2026-04-09

pipeline_executions 테이블에 task_progress JSONB 컬럼 추가.
DAG 태스크별 실행 진행 상태(시작/완료 시각, 입출력 이미지 수)를 기록한다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision: str = "006_add_task_progress"
down_revision: Union[str, None] = "005_add_annotation_meta_file"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pipeline_executions",
        sa.Column(
            "task_progress",
            JSONB,
            nullable=True,
            comment="DAG 태스크별 진행 상태. {task_name: {status, started_at, finished_at, ...}}",
        ),
    )


def downgrade() -> None:
    op.drop_column("pipeline_executions", "task_progress")
