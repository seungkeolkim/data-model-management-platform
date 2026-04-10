"""버전 포맷 마이그레이션: v{major}.{minor}.{patch} → {major}.{minor}

Revision ID: 007_migrate_version_format
Revises: 006_add_task_progress
Create Date: 2026-04-09

기존 3단계 semver(v1.0.0, v1.0.1 등)를 2단계 형식(1.0, 2.0 등)으로 변환.
같은 group_id+split 내에서 created_at 순으로 1.0, 2.0, 3.0 ... 을 부여한다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "007_migrate_version_format"
down_revision: Union[str, None] = "006_add_task_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    group_id + split 그룹 단위로 created_at 오름차순 정렬 후
    1.0, 2.0, 3.0 ... 으로 버전을 재부여한다.
    """
    conn = op.get_bind()

    # 모든 고유 (group_id, split) 조합 조회
    groups = conn.execute(
        sa.text(
            "SELECT DISTINCT group_id, split FROM datasets "
            "WHERE deleted_at IS NULL "
            "ORDER BY group_id, split"
        )
    ).fetchall()

    for group_id, split in groups:
        # 해당 그룹+split의 데이터셋을 생성순 정렬
        datasets = conn.execute(
            sa.text(
                "SELECT id FROM datasets "
                "WHERE group_id = :gid AND split = :sp AND deleted_at IS NULL "
                "ORDER BY created_at ASC"
            ),
            {"gid": group_id, "sp": split},
        ).fetchall()

        for idx, (dataset_id,) in enumerate(datasets, start=1):
            new_version = f"{idx}.0"
            conn.execute(
                sa.text("UPDATE datasets SET version = :ver WHERE id = :did"),
                {"ver": new_version, "did": dataset_id},
            )


def downgrade() -> None:
    """
    역마이그레이션: {major}.0 → v{major}.0.0 형태로 복원.
    원본 patch 번호는 복구 불가하므로 근사 변환만 수행한다.
    """
    conn = op.get_bind()
    datasets = conn.execute(
        sa.text("SELECT id, version FROM datasets WHERE deleted_at IS NULL")
    ).fetchall()

    for dataset_id, version in datasets:
        try:
            parts = version.split(".")
            old_version = f"v{parts[0]}.{parts[1]}.0"
        except (IndexError, ValueError):
            old_version = "v1.0.0"
        conn.execute(
            sa.text("UPDATE datasets SET version = :ver WHERE id = :did"),
            {"ver": old_version, "did": dataset_id},
        )
