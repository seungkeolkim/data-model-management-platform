"""initial schema - all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-02-19

전체 스키마 초기 생성:
  - dataset_groups, datasets, dataset_lineage
  - manipulators, pipeline_executions
  - objectives, recipes, solutions, solution_versions, training_jobs  (2차 대비)
  - dataset_group_summary Materialized View
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # 1차 — 데이터셋 관리
    # =========================================================================

    op.create_table(
        "dataset_groups",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("dataset_type", sa.String(20), nullable=False,
                  comment="RAW | SOURCE | PROCESSED | FUSION"),
        sa.Column("annotation_format", sa.String(30), nullable=False, server_default="NONE",
                  comment="COCO | YOLO | ATTR_JSON | CLS_FOLDER | CUSTOM | NONE"),
        sa.Column("task_types", postgresql.JSONB, nullable=True),
        sa.Column("modality", sa.String(30), nullable=False, server_default="RGB",
                  comment="RGB | THERMAL | DEPTH | MULTISPECTRAL"),
        sa.Column("source_origin", sa.String(500), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("extra", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_dataset_groups_name", "dataset_groups", ["name"])
    op.create_index("ix_dataset_groups_dataset_type", "dataset_groups", ["dataset_type"])

    op.create_table(
        "datasets",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("dataset_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("split", sa.String(10), nullable=False, server_default="NONE",
                  comment="TRAIN | VAL | TEST | NONE"),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("annotation_format", sa.String(30), nullable=True),
        sa.Column("storage_uri", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING",
                  comment="PENDING | PROCESSING | READY | ERROR"),
        sa.Column("image_count", sa.Integer, nullable=True),
        sa.Column("class_count", sa.Integer, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "split", "version", name="uq_dataset_group_split_version"),
    )
    op.create_index("ix_datasets_group_id", "datasets", ["group_id"])
    op.create_index("ix_datasets_status", "datasets", ["status"])

    op.create_table(
        "dataset_lineage",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("child_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transform_config", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_lineage_parent_id", "dataset_lineage", ["parent_id"])
    op.create_index("ix_lineage_child_id", "dataset_lineage", ["child_id"])

    op.create_table(
        "manipulators",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("category", sa.String(30), nullable=False,
                  comment="FILTER | AUGMENT | FORMAT_CONVERT | MERGE | SAMPLE | REMAP"),
        sa.Column("scope", postgresql.JSONB, nullable=False),
        sa.Column("compatible_task_types", postgresql.JSONB, nullable=True),
        sa.Column("compatible_annotation_fmts", postgresql.JSONB, nullable=True),
        sa.Column("output_annotation_fmt", sa.String(30), nullable=True),
        sa.Column("params_schema", postgresql.JSONB, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE",
                  comment="ACTIVE | EXPERIMENTAL | DEPRECATED"),
        sa.Column("version", sa.String(20), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "pipeline_executions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("output_dataset_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING",
                  comment="PENDING | RUNNING | DONE | FAILED"),
        sa.Column("current_stage", sa.String(50), nullable=True),
        sa.Column("processed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP, nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pipeline_executions_status", "pipeline_executions", ["status"])
    op.create_index("ix_pipeline_executions_output_dataset_id",
                    "pipeline_executions", ["output_dataset_id"])

    # =========================================================================
    # 2차 대비 — 모델 학습 관리 (빈 테이블)
    # =========================================================================

    op.create_table(
        "objectives",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "recipes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("objective_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("objectives.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False,
                  comment="ULTRALYTICS | MMYOLO | CUSTOM"),
        sa.Column("base_config", postgresql.JSONB, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "solutions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("recipe_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("train_dataset_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("val_dataset_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("test_dataset_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "solution_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("solution_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("solutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("override_config", postgresql.JSONB, nullable=True),
        sa.Column("gpu_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING",
                  comment="PENDING | QUEUED | RUNNING | DONE | FAILED"),
        sa.Column("mlflow_run_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "training_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("solution_version_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("solution_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("container_id", sa.String(255), nullable=True,
                  comment="Docker container ID (2차) / K8S Pod name (3차)"),
        sa.Column("gpu_ids", postgresql.JSONB, nullable=True),
        sa.Column("started_at", sa.TIMESTAMP, nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP, nullable=True),
        sa.Column("metrics", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )

    # =========================================================================
    # Materialized View — dataset_group_summary
    # =========================================================================
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


def downgrade() -> None:
    # Materialized View 삭제
    op.execute("DROP MATERIALIZED VIEW IF EXISTS dataset_group_summary;")

    # 2차 대비 테이블
    op.drop_table("training_jobs")
    op.drop_table("solution_versions")
    op.drop_table("solutions")
    op.drop_table("recipes")
    op.drop_table("objectives")

    # 1차 테이블
    op.drop_table("pipeline_executions")
    op.drop_table("manipulators")
    op.drop_table("dataset_lineage")
    op.drop_table("datasets")
    op.drop_table("dataset_groups")
