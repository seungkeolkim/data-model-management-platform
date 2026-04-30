"""PipelineFamily.color 추가 + 기존 family 들 랜덤 색상 백필

Revision ID: 033_pipeline_family_color
Revises: 032_pipeline_family_version
Create Date: 2026-04-29

배경:
    Pipeline 목록에서 family 가 늘어나면 이름만으로 빠르게 구분하기 어렵다.
    family 별 시각 구분용 색상 컬럼 추가. 신규 family 는 랜덤 색상 자동 할당,
    수정 시 사용자가 컬러 팔레트로 변경 가능.

변경 내용:
    - pipeline_families.color VARCHAR(7) NOT NULL — `#RRGGBB` 형태.
    - 기존 family 행은 마이그레이션이 랜덤 hex 로 백필.
"""
from __future__ import annotations

import random
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "033_pipeline_family_color"
down_revision: Union[str, None] = "032_pipeline_family_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _random_color_hex() -> str:
    """가독성 좋은 mid-tone 랜덤 색 (각 채널 80~200). 너무 어둡지/밝지 않게."""
    return "#{:02x}{:02x}{:02x}".format(
        random.randint(80, 200),
        random.randint(80, 200),
        random.randint(80, 200),
    )


def upgrade() -> None:
    conn = op.get_bind()

    # 1) 컬럼 추가 (먼저 nullable=True 로 추가 후 백필 → NOT NULL 전환)
    op.add_column(
        "pipeline_families",
        sa.Column(
            "color",
            sa.String(7),
            nullable=True,
            comment="Family 시각 구분 색 (`#RRGGBB`). 신규 생성 시 자동 할당, 사용자 수정 가능.",
        ),
    )

    # 2) 기존 family 들 색상 백필 — 랜덤 hex
    rows = conn.execute(sa.text("SELECT id FROM pipeline_families")).fetchall()
    for (family_id,) in rows:
        conn.execute(
            sa.text("UPDATE pipeline_families SET color = :color WHERE id = :id"),
            {"id": family_id, "color": _random_color_hex()},
        )

    # 3) NOT NULL 전환
    op.alter_column("pipeline_families", "color", nullable=False)


def downgrade() -> None:
    op.drop_column("pipeline_families", "color")
