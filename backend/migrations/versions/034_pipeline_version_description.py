"""PipelineVersion.description 추가 — version 단위 사용자 메모

Revision ID: 034_pipeline_version_description
Revises: 033_pipeline_family_color
Create Date: 2026-04-29

배경:
    Pipeline (concept) 에는 이미 description 컬럼이 있지만, 같은 Pipeline 안에
    누적되는 PipelineVersion 별로 "이 버전에서 무엇을 바꿨는가" 를 기록할 곳이
    없었다. config 가 immutable 인 만큼 변경 의도는 사람이 직접 적어줘야
    추적 가능. concept-level description 과 별개로 version-level description
    컬럼을 추가한다.

변경 내용:
    - pipeline_versions.description TEXT NULL — `#RRGGBB` 같은 패턴 제약 없음.
      백필 없음 (NULL 허용 — 기존 행은 미작성 상태).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "034_pipeline_version_description"
down_revision: Union[str, None] = "033_pipeline_family_color"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pipeline_versions",
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
            comment=(
                "이 버전에서 변경한 의도/내용. config 는 immutable 이라 변경 사유는"
                " 사람이 적어줘야 한다. concept-level description (pipelines.description)"
                " 과 독립."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("pipeline_versions", "description")
