"""Pipeline / PipelineRun / PipelineAutomation 3 엔티티 분리

Revision ID: 031_split_pipeline_entities
Revises: 030_dataset_three_tier_split
Create Date: 2026-04-24

NOTE: revision ID 는 alembic_version.version_num (VARCHAR(32)) 길이 제약 때문에
      `031_split_pipeline_entities` (27 chars) 로 유지. 파일명도 동일.

배경:
    핸드오프 027 — "Pipeline = Automation 엔트리" 단일 테이블 모델의 개념 섞임을
    해소하기 위해 3 엔티티로 분리. 동시에 "2안 (run-time version 해석)" 으로 전환.

    - Pipeline              (정적 템플릿, config immutable) — 신규 테이블
    - PipelineRun           (동적 immutable run) — 기존 pipeline_executions → rename
    - PipelineAutomation    (Pipeline 과 1:0..1 runner 등록) — 신규 테이블

    설계서 v7.10 승격 예정. 상세 설계: 027 §2 ~ §6 + §12 실착수 결정.

핵심 설계 결정 (핸드오프 027 §12 에서 최종 확정):
    - §12-3 PipelineAutomation soft delete (is_active + deleted_at). FK 유지.
    - §12-9 Pipeline.input_split_id top-level FK **없음** (C 채택).
        config.tasks[*].inputs 의 source:<split_id> 가 유일 진리. output_split_id 만 단일 FK.
        JSONB GIN 인덱스는 당장 안 만들고 성능 이슈 실측 시 추가 (아래 주석 블록 참조).

변경 내용:
    신규 테이블:
        - pipelines
            · UNIQUE(name, version)
            · output_split_id UUID NOT NULL FK → dataset_splits.id (ON DELETE RESTRICT)
            · config JSONB NOT NULL (§6-1 immutable)
            · is_active BOOL (soft delete, §6-2)
        - pipeline_automations
            · pipeline_id UUID FK → pipelines.id
            · partial unique index: is_active=TRUE 일 때만 pipeline_id 유일 (1:0..1)
            · is_active + deleted_at (§12-3 soft delete)

    기존 테이블 변경 (pipeline_executions → pipeline_runs):
        - 컬럼 rename: config → transform_config (027 §2-2 일관성)
        - 신규 컬럼:
            · pipeline_id UUID NOT NULL FK → pipelines.id (ON DELETE RESTRICT)
            · automation_id UUID NULL FK → pipeline_automations.id (ON DELETE RESTRICT)
            · resolved_input_versions JSONB NULL
            · trigger_kind VARCHAR(40) NOT NULL DEFAULT 'manual_from_editor'
            · automation_trigger_source VARCHAR(40) NULL
            · automation_batch_id UUID NULL
            · pipeline_image_url VARCHAR(500) NULL
        - 테이블 rename: pipeline_executions → pipeline_runs
        - 외부 FK 참조 없음 (사전 확인 완료)

백필 전략:
    본 migration 은 v7.10 신규 도입 시점이라 기존 pipeline_executions 가 비어있는
    환경을 가정한다 (DB 초기화 후 적용). pipeline_runs.pipeline_id NOT NULL 제약은
    빈 테이블에서 즉시 추가된다.

    만약 기존 데이터가 있으면 alter_column 단계에서 NOT NULL 위반이 발생하므로,
    그 경우 사용자가 별도 정책으로 수동 백필 후 재시도해야 한다.

downgrade:
    역순. pipeline_runs → pipeline_executions rename 복구 + 신규 컬럼 drop +
    transform_config → config rename 복구 + pipeline_automations / pipelines DROP.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "031_split_pipeline_entities"
down_revision: Union[str, None] = "030_dataset_three_tier_split"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    # pgcrypto 는 025 (030 migration) 에서 이미 로드됨. 안전하게 다시 확인.
    connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    # ==========================================================================
    # 1) pipelines 테이블 신규 생성 (027 §2-1 + §12-9 C)
    # ==========================================================================
    op.create_table(
        "pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "name", sa.String(255), nullable=False,
            comment="사용자 명시 또는 {output_group}_{output_split} 자동 생성 (§12-2)",
        ),
        sa.Column(
            "version", sa.String(20), nullable=False,
            server_default=sa.text("'1.0'"),
            comment="{major}.{minor} — 사용자 명시로만 major++ (§3-2, hash 판정 없음)",
        ),
        sa.Column("description", sa.Text, nullable=True),
        # §12-9 C 확정: input_split_id top-level FK 없음.
        # multi-input 이 흔하고 (det_merge_datasets / cls_merge_datasets),
        # config.tasks[*].inputs 의 source:<split_id> 가 유일 진리.
        sa.Column(
            "output_split_id", postgresql.UUID(as_uuid=False),
            sa.ForeignKey("dataset_splits.id", ondelete="RESTRICT"),
            nullable=False,
            comment="output 은 항상 단일 DatasetSplit — FK 유지. §12-9",
        ),
        sa.Column(
            "config", postgresql.JSONB, nullable=False,
            comment=(
                "PipelineConfig JSONB 스냅샷 (schema_version=2). "
                "생성 후 절대 수정 금지 — 027 §6-1 immutable"
            ),
        ),
        sa.Column(
            "task_type", sa.String(30), nullable=False,
            comment="DETECTION | CLASSIFICATION | SEGMENTATION | ZERO_SHOT — 생성 시점 스냅샷",
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False,
            server_default=sa.text("TRUE"),
            comment="soft delete. 027 §6-2.",
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP, nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP, nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", "version", name="uq_pipeline_name_version"),
    )
    op.create_index(
        "ix_pipelines_name_is_active", "pipelines", ["name", "is_active"]
    )

    # ──────────────────────────────────────────────────────────────────────────
    # NOTE (§12-9): JSONB 스캔 성능 이슈 발생 시 아래 GIN 인덱스 추가.
    #
    # 현 규모 (수십 개 Pipeline) 에서는 불필요. "이 split 을 쓰는 Pipeline 찾기"
    # (chaining 분석 / automation triggering 훅) 쿼리가 느려지면 다음 한 줄로 해결:
    #
    #     CREATE INDEX ix_pipelines_config_gin ON pipelines
    #         USING GIN (config jsonb_path_ops);
    #
    # 나중에 pipeline_inputs(pipeline_id, split_id) 조인 테이블 (B 안) 로 격상해야
    # 할 수도 있음 — Pipeline.config immutable 덕에 백필 작업으로 하루에 전환 가능.
    # ──────────────────────────────────────────────────────────────────────────

    # ==========================================================================
    # 2) pipeline_automations 테이블 신규 생성 (027 §2-3 + §12-3 soft delete)
    # ==========================================================================
    op.create_table(
        "pipeline_automations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "pipeline_id", postgresql.UUID(as_uuid=False),
            sa.ForeignKey("pipelines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default=sa.text("'stopped'"),
            comment="stopped | active | error",
        ),
        sa.Column(
            "mode", sa.String(20), nullable=True,
            comment="polling | triggering | NULL (stopped 시)",
        ),
        sa.Column(
            "poll_interval", sa.String(10), nullable=True,
            comment="10m | 1h | 6h | 24h | NULL (polling 외)",
        ),
        sa.Column(
            "error_reason", sa.String(50), nullable=True,
            comment="CYCLE_DETECTED | PIPELINE_DELETED | INPUT_GROUP_NOT_FOUND 등",
        ),
        sa.Column(
            "last_seen_input_versions", postgresql.JSONB, nullable=True,
            comment="{split_id: version}. 자동 실행 성공 시 갱신. delta 판정 기준점",
        ),
        # §12-3 soft delete — FK 참조는 row 가 살아있어 영원히 유효 (dangling 아님)
        sa.Column(
            "is_active", sa.Boolean, nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "deleted_at", sa.TIMESTAMP, nullable=True,
            comment="soft delete 시각. NULL 이면 활성",
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP, nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP, nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # 1:0..1 관계 — soft delete 된 automation 은 제약 밖이라 같은 pipeline 에
    # 새 automation 등록 가능. Pipeline 의 is_active 와 독립.
    op.execute(
        "CREATE UNIQUE INDEX uq_pipeline_automation_active_pipeline "
        "ON pipeline_automations (pipeline_id) WHERE is_active = TRUE"
    )

    # ==========================================================================
    # 3) pipeline_executions 컬럼 확장
    # ==========================================================================

    # 3-1. config → transform_config 컬럼명 변경 (027 §2-2 일관성)
    op.alter_column(
        "pipeline_executions", "config",
        new_column_name="transform_config",
    )

    # 3-2. 신규 컬럼 추가 (pipeline_id 는 초기 nullable — 백필 후 NOT NULL 전환)
    op.add_column(
        "pipeline_executions",
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "pipeline_executions",
        sa.Column("automation_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "pipeline_executions",
        sa.Column(
            "resolved_input_versions", postgresql.JSONB, nullable=True,
            comment="{split_id: version} — run 제출 시점의 input 버전 해석",
        ),
    )
    op.add_column(
        "pipeline_executions",
        sa.Column(
            "trigger_kind", sa.String(40), nullable=False,
            server_default=sa.text("'manual_from_editor'"),
            comment="manual_from_editor | automation_auto | automation_manual_rerun (027 §9-7)",
        ),
    )
    op.add_column(
        "pipeline_executions",
        sa.Column(
            "automation_trigger_source", sa.String(40), nullable=True,
            comment="polling | triggering | manual_rerun | NULL (manual_from_editor 시)",
        ),
    )
    op.add_column(
        "pipeline_executions",
        sa.Column("automation_batch_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "pipeline_executions",
        sa.Column(
            "pipeline_image_url", sa.String(500), nullable=True,
            comment="027 §2-2 명시 — 향후 DAG 이미지 URL 저장",
        ),
    )

    # ==========================================================================
    # 4) FK 제약 추가
    # ==========================================================================
    # NOTE: 본 migration 은 v7.10 신규 도입 시점이라 기존 pipeline_executions 가
    # 비어있는 환경 (DB 초기화 직후) 을 가정한다. 만약 기존 데이터가 있으면
    # pipeline_id NOT NULL 제약이 즉시 위반되므로, 그 경우 사용자가 별도 정책으로
    # 수동 백필해야 한다.
    op.alter_column("pipeline_executions", "pipeline_id", nullable=False)
    op.create_foreign_key(
        "fk_pipeline_executions_pipeline_id",
        "pipeline_executions", "pipelines",
        ["pipeline_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_pipeline_executions_automation_id",
        "pipeline_executions", "pipeline_automations",
        ["automation_id"], ["id"],
        ondelete="RESTRICT",
    )

    # ==========================================================================
    # 5) pipeline_executions → pipeline_runs 테이블 rename
    #    외부 FK 참조는 없으므로 단순 rename.
    # ==========================================================================
    op.rename_table("pipeline_executions", "pipeline_runs")


def downgrade() -> None:
    # 역순으로 되돌림.
    # 5) 테이블명 복구
    op.rename_table("pipeline_runs", "pipeline_executions")

    # 4) FK 제약 해제
    op.drop_constraint(
        "fk_pipeline_executions_automation_id",
        "pipeline_executions", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_pipeline_executions_pipeline_id",
        "pipeline_executions", type_="foreignkey",
    )

    # 3-2) 신규 컬럼 DROP (추가 역순)
    op.drop_column("pipeline_executions", "pipeline_image_url")
    op.drop_column("pipeline_executions", "automation_batch_id")
    op.drop_column("pipeline_executions", "automation_trigger_source")
    op.drop_column("pipeline_executions", "trigger_kind")
    op.drop_column("pipeline_executions", "resolved_input_versions")
    op.drop_column("pipeline_executions", "automation_id")
    op.drop_column("pipeline_executions", "pipeline_id")

    # 3-1) transform_config → config rename 복구
    op.alter_column(
        "pipeline_executions", "transform_config",
        new_column_name="config",
    )

    # 2) pipeline_automations DROP
    op.drop_index(
        "uq_pipeline_automation_active_pipeline",
        table_name="pipeline_automations",
    )
    op.drop_table("pipeline_automations")

    # 1) pipelines DROP
    op.drop_index("ix_pipelines_name_is_active", table_name="pipelines")
    op.drop_table("pipelines")
