"""Dataset 3계층 분리 — DatasetGroup → DatasetSplit → DatasetVersion

Revision ID: 030_dataset_three_tier_split
Revises: 029_backfill_group_head_schema
Create Date: 2026-04-23

배경:
    Automation 실착수 전에 정적(static) / 동적(dynamic) 경계를 테이블 단위로
    구조화한다. split 을 정적 슬롯 엔티티(DatasetSplit)로 승격시키면 Pipeline 이
    "특정 그룹의 TRAIN split 최신 버전" 을 FK 무결성 하에 참조할 수 있다.

    핸드오프 025 §2 + 설계서 v7.9(본 마이그레이션 이후 승격).

변경 내용:
    - 신규 테이블: dataset_splits — UNIQUE(group_id, split)
    - 테이블 rename: datasets → dataset_versions
    - 컬럼 재배치: datasets.(group_id, split) → dataset_versions.split_id
    - unique constraint 교체: (group_id, split, version) → (split_id, version)
    - 외부 FK 참조: pipeline_executions.output_dataset_id,
      solutions.(train|val|test)_dataset_id, dataset_lineage.(parent|child)_id
      전부 ALTER TABLE RENAME 을 따라 자동 추종 (PostgreSQL OID 기반)

백필 전략:
    1. DISTINCT (group_id, split) 조합 추출 → dataset_splits 1행씩 INSERT
    2. datasets.split_id 를 (group_id, split) 매핑으로 UPDATE
    3. NOT NULL + FK 걸고, 구 컬럼들 DROP
    4. 마지막에 테이블 rename

downgrade:
    역순. dataset_versions → datasets rename 복구 후 group_id / split 컬럼 복원,
    split_id 역매핑으로 채운 뒤 dataset_splits DROP.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "030_dataset_three_tier_split"
down_revision: Union[str, None] = "029_backfill_group_head_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    # ==========================================================================
    # 0) dataset_group_summary MATERIALIZED VIEW 선제 삭제
    #    001 에서 datasets.group_id / split 에 의존하는 MV 를 만들어 둔 상태.
    #    컬럼 DROP 전에 먼저 날리고, 마지막에 신규 스키마(split_id → dataset_splits →
    #    dataset_groups 2단 JOIN) 로 재생성한다.
    # ==========================================================================
    op.execute("DROP MATERIALIZED VIEW IF EXISTS dataset_group_summary")

    # ==========================================================================
    # 1) dataset_splits 테이블 신규 생성
    #    - group_id 당 split 은 유일 (UNIQUE)
    #    - created_at 만 두고 updated_at 은 생략 (정적 엔티티, 핸드오프 025 §3-2)
    # ==========================================================================
    op.create_table(
        "dataset_splits",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("dataset_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "split", sa.String(10), nullable=False,
            comment="TRAIN | VAL | TEST | NONE",
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP, nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("group_id", "split", name="uq_dataset_split_group_split"),
    )
    op.create_index(
        "ix_dataset_splits_group_id", "dataset_splits", ["group_id"],
    )

    # ==========================================================================
    # 2) 기존 datasets 에서 DISTINCT (group_id, split) 추출해 dataset_splits 행 생성
    #    - gen_random_uuid() 는 pgcrypto 필요하지만, 현 인프라에 이미 로드되어 있음
    #      (dataset_groups.id 기본값이 UUID 생성이므로). 혹시 미로드 환경 대비로
    #      명시 CREATE EXTENSION 을 한 줄 둔다 (idempotent).
    # ==========================================================================
    connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    connection.execute(
        sa.text(
            """
            INSERT INTO dataset_splits (id, group_id, split, created_at)
            SELECT gen_random_uuid(), group_id, split, MIN(created_at)
            FROM datasets
            GROUP BY group_id, split
            """
        )
    )

    # ==========================================================================
    # 3) datasets.split_id 컬럼 추가 (일단 nullable 로 생성)
    # ==========================================================================
    op.add_column(
        "datasets",
        sa.Column("split_id", postgresql.UUID(as_uuid=False), nullable=True),
    )

    # ==========================================================================
    # 4) datasets.split_id UPDATE — (group_id, split) 매핑으로 채움
    # ==========================================================================
    connection.execute(
        sa.text(
            """
            UPDATE datasets AS d
            SET split_id = s.id
            FROM dataset_splits AS s
            WHERE d.group_id = s.group_id
              AND d.split    = s.split
            """
        )
    )

    # 방어적 검증: split_id 가 NULL 인 행이 남아 있으면 실패로 전환.
    null_remaining = connection.execute(
        sa.text("SELECT COUNT(*) FROM datasets WHERE split_id IS NULL")
    ).scalar_one()
    if null_remaining:
        raise RuntimeError(
            f"[030] split_id 백필 불일치 — NULL 잔존 {null_remaining} 건. "
            "업그레이드를 중단한다."
        )

    # ==========================================================================
    # 5) NOT NULL + FK 제약 + 인덱스
    # ==========================================================================
    op.alter_column("datasets", "split_id", nullable=False)
    op.create_foreign_key(
        "fk_datasets_split_id_dataset_splits",
        source_table="datasets",
        referent_table="dataset_splits",
        local_cols=["split_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_datasets_split_id", "datasets", ["split_id"])

    # ==========================================================================
    # 6) unique constraint 교체
    #    (group_id, split, version) DROP → (split_id, version) 신설
    # ==========================================================================
    op.drop_constraint(
        "uq_dataset_group_split_version", "datasets", type_="unique",
    )
    op.create_unique_constraint(
        "uq_dataset_version_split_version", "datasets", ["split_id", "version"],
    )

    # ==========================================================================
    # 7) 기존 group_id / split 컬럼 제거
    #    - 관련 인덱스 (ix_datasets_group_id) 도 같이 제거
    #    - group_id FK 제약 (익명) 은 DROP COLUMN 이 자동 정리
    # ==========================================================================
    op.drop_index("ix_datasets_group_id", table_name="datasets")
    op.drop_column("datasets", "group_id")
    op.drop_column("datasets", "split")

    # ==========================================================================
    # 8) 테이블 rename — datasets → dataset_versions
    #    외부 FK (pipeline_executions.output_dataset_id, solutions.*_dataset_id,
    #    dataset_lineage.parent_id/child_id) 는 PostgreSQL OID 기반 참조이므로
    #    자동 추종한다. 인덱스 이름(ix_datasets_*) 도 자동 따라가지만, 의미
    #    명시를 위해 수동 rename 한다.
    # ==========================================================================
    op.rename_table("datasets", "dataset_versions")

    op.execute(
        "ALTER INDEX IF EXISTS ix_datasets_status RENAME TO ix_dataset_versions_status"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_datasets_split_id RENAME TO ix_dataset_versions_split_id"
    )
    # PK / unique 제약 이름도 일관성을 위해 정리.
    op.execute(
        "ALTER TABLE dataset_versions RENAME CONSTRAINT "
        "uq_dataset_version_split_version TO uq_dataset_versions_split_version"
    )
    op.execute(
        "ALTER TABLE dataset_versions RENAME CONSTRAINT "
        "fk_datasets_split_id_dataset_splits TO fk_dataset_versions_split_id"
    )
    # PK 이름은 PostgreSQL 이 자동으로 datasets_pkey 로 생성했을 가능성이 높으므로
    # 방어적으로 rename 시도.
    op.execute(
        "ALTER TABLE dataset_versions RENAME CONSTRAINT "
        "datasets_pkey TO dataset_versions_pkey"
    )

    # ==========================================================================
    # 9) dataset_group_summary MATERIALIZED VIEW 재생성 — 신규 3계층 스키마 기반
    #    기존 외부 응답 shape 를 유지 (datasets 배열에 split 을 그대로 노출).
    #    JOIN 경로: dataset_groups → dataset_splits → dataset_versions
    # ==========================================================================
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS dataset_group_summary AS
        SELECT
            dg.id         AS group_id,
            dg.name,
            dg.dataset_type,
            dg.annotation_format,
            dg.task_types,
            dg.modality,
            dg.description,
            dg.source_origin,
            dg.created_at AS group_created_at,
            dg.updated_at AS group_updated_at,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id',          dv.id,
                        'split',       ds.split,
                        'version',     dv.version,
                        'status',      dv.status,
                        'image_count', dv.image_count,
                        'class_count', dv.class_count,
                        'storage_uri', dv.storage_uri,
                        'created_at',  dv.created_at
                    ) ORDER BY ds.split, dv.version
                ) FILTER (WHERE dv.id IS NOT NULL),
                '[]'::jsonb
            ) AS datasets
        FROM dataset_groups dg
        LEFT JOIN dataset_splits   ds ON ds.group_id   = dg.id
        LEFT JOIN dataset_versions dv ON dv.split_id   = ds.id
        GROUP BY dg.id
        WITH DATA;
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
            uix_dataset_group_summary_group_id
        ON dataset_group_summary (group_id);
    """)


def downgrade() -> None:
    # MV 먼저 삭제 — 컬럼 복원 시 충돌 방지.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS dataset_group_summary")

    connection = op.get_bind()

    # ==========================================================================
    # 역순: dataset_versions → datasets rename 후 group_id/split 컬럼 복원
    # ==========================================================================
    op.execute(
        "ALTER TABLE dataset_versions RENAME CONSTRAINT "
        "dataset_versions_pkey TO datasets_pkey"
    )
    op.execute(
        "ALTER TABLE dataset_versions RENAME CONSTRAINT "
        "fk_dataset_versions_split_id TO fk_datasets_split_id_dataset_splits"
    )
    op.execute(
        "ALTER TABLE dataset_versions RENAME CONSTRAINT "
        "uq_dataset_versions_split_version TO uq_dataset_version_split_version"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_dataset_versions_split_id RENAME TO ix_datasets_split_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_dataset_versions_status RENAME TO ix_datasets_status"
    )

    op.rename_table("dataset_versions", "datasets")

    # group_id / split 컬럼 복원 (초기 nullable).
    op.add_column(
        "datasets",
        sa.Column("group_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "datasets",
        sa.Column(
            "split", sa.String(10), nullable=True,
            comment="TRAIN | VAL | TEST | NONE",
        ),
    )

    # split_id 역매핑 — dataset_splits 에서 (group_id, split) 를 가져와 복원.
    connection.execute(
        sa.text(
            """
            UPDATE datasets AS d
            SET group_id = s.group_id,
                split    = s.split
            FROM dataset_splits AS s
            WHERE d.split_id = s.id
            """
        )
    )

    null_remaining = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM datasets "
            "WHERE group_id IS NULL OR split IS NULL"
        )
    ).scalar_one()
    if null_remaining:
        raise RuntimeError(
            f"[030 downgrade] (group_id, split) 역복원 불일치 — NULL {null_remaining} 건."
        )

    # NOT NULL + FK (group_id) + 구 인덱스 복원.
    op.alter_column("datasets", "group_id", nullable=False)
    op.alter_column(
        "datasets", "split", nullable=False, server_default="NONE",
    )
    op.create_foreign_key(
        None,
        source_table="datasets",
        referent_table="dataset_groups",
        local_cols=["group_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_datasets_group_id", "datasets", ["group_id"])

    # unique constraint 원복.
    op.drop_constraint(
        "uq_dataset_version_split_version", "datasets", type_="unique",
    )
    op.create_unique_constraint(
        "uq_dataset_group_split_version", "datasets",
        ["group_id", "split", "version"],
    )

    # split_id 제거.
    op.drop_index("ix_datasets_split_id", table_name="datasets")
    op.drop_constraint(
        "fk_datasets_split_id_dataset_splits", "datasets", type_="foreignkey",
    )
    op.drop_column("datasets", "split_id")

    # dataset_splits 테이블 삭제.
    op.drop_index("ix_dataset_splits_group_id", table_name="dataset_splits")
    op.drop_table("dataset_splits")

    # 구 MV 재생성 (001 원본과 동일한 SQL).
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS dataset_group_summary AS
        SELECT
            dg.id           AS group_id,
            dg.name,
            dg.dataset_type,
            dg.annotation_format,
            dg.task_types,
            dg.modality,
            dg.description,
            dg.source_origin,
            dg.created_at   AS group_created_at,
            dg.updated_at   AS group_updated_at,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id',           ds.id,
                        'split',        ds.split,
                        'version',      ds.version,
                        'status',       ds.status,
                        'image_count',  ds.image_count,
                        'class_count',  ds.class_count,
                        'storage_uri',  ds.storage_uri,
                        'created_at',   ds.created_at
                    ) ORDER BY ds.split, ds.version
                ) FILTER (WHERE ds.id IS NOT NULL),
                '[]'::jsonb
            ) AS datasets
        FROM dataset_groups dg
        LEFT JOIN datasets ds ON ds.group_id = dg.id
        GROUP BY dg.id
        WITH DATA;
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
            uix_dataset_group_summary_group_id
        ON dataset_group_summary (group_id);
    """)
