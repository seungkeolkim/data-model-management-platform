"""Pipeline family + version 분리 + source format v3

Revision ID: 032_pipeline_family_version
Revises: 031_split_pipeline_entities
Create Date: 2026-04-28

NOTE: revision ID 는 alembic_version.version_num (VARCHAR(32)) 길이 제약으로
      `032_pipeline_family_version` (29 chars).

배경:
    v7.10 의 `pipelines` 단일 테이블이 "개념 정체성 + 버전 인스턴스" 두 책임을 겸하고
    있었음. v7.11 은 이를 다음 3 계층으로 분리한다.

        PipelineFamily   — 사용자 즐겨찾기 폴더 (자유 이동, NULL 허용 FK)
        Pipeline         — 개념 정체성 (name 전역 UNIQUE, output_split / task_type 고정)
        PipelineVersion  — config + version (immutable, 모 Pipeline 영구 소속)

    동시에 source format 을 v3 로 bump:
        v2 :  "source:<UUID>"                     (의미가 위치 의존적이어서 모호)
        v3 :  "source:dataset_split:<UUID>"       (Pipeline.config — 템플릿)
              "source:dataset_version:<UUID>"     (PipelineRun.transform_config — resolved)

    핸드오프 027 §12-9 의 "source:<id> 가 유일 진리" 원칙은 유지하되, 그 토큰에
    type 차원을 명시화. 사용자가 PipelineRun JSON 을 복사해 에디터로 import 할 때
    의미 분기가 가능해진다.

변경 내용:
    신규 테이블:
        - pipeline_families (id PK, name UNIQUE, description, created_at/updated_at)
        - pipeline_versions (id PK, pipeline_id FK, version, config JSONB, is_active,
          created_at/updated_at, UNIQUE(pipeline_id, version))

    pipelines 테이블 재구성:
        - version / config 컬럼 분리 → pipeline_versions 로 이동
        - family_id NULL 허용 FK → pipeline_families.id 추가
        - name 단독 UNIQUE (전역) — UNIQUE(name, version) 제거
        - output_split_id / task_type / description / is_active / 타임스탬프는 유지

    pipeline_runs:
        - pipeline_id → pipeline_version_id (rename + FK 대상 교체 → pipeline_versions)
        - transform_config 안의 source 토큰을 v3 (dataset_version 접두) 로 일괄 rewrite
        - schema_version 2 → 3 bump

    pipeline_automations:
        - pipeline_id → pipeline_version_id (rename + FK 대상 교체)
        - partial unique index 도 새 컬럼 기준으로 재생성

데이터 보존 전략:
    `pipeline_versions.id` 를 기존 `pipelines.id` 그대로 승계. 이렇게 하면
    pipeline_runs / pipeline_automations 의 기존 pipeline_id 값이 그대로
    pipeline_version_id 로 의미 전환되어 데이터 매핑 불필요.

    pipelines (concept) 의 id 는 새로 발급. 같은 name 의 여러 version 들은 한
    concept 로 묶인다 (현 DB 에는 모두 단일 version 이라 1:1 매핑).

downgrade:
    역순. v3 prefix 제거 + concept/version 합치기.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "032_pipeline_family_version"
down_revision: Union[str, None] = "031_split_pipeline_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ─────────────────────────────────────────────────────────────────────────────
# Source format rewrite helpers
# ─────────────────────────────────────────────────────────────────────────────

_V3_PREFIXES = ("source:dataset_split:", "source:dataset_version:")


def _rewrite_source_to_v3(config: Any, source_type: str) -> Any:
    """
    config 의 schema_version 을 3 으로 올리고 inputs 의 `source:<id>` 토큰을
    v3 포맷으로 변환.

    `source_type`:
        - "dataset_split"   — Pipeline.config 측 (사용자 spec)
        - "dataset_version" — PipelineRun.transform_config 측 (resolved 스냅샷)

    이미 v3 포맷이면 그대로 둠 (idempotent). schema_version 만 3 으로 보장.
    """
    if not isinstance(config, dict):
        return config

    new_config = dict(config)
    new_config["schema_version"] = 3

    tasks = new_config.get("tasks")
    if isinstance(tasks, dict):
        new_tasks: dict[str, Any] = {}
        for task_name, task in tasks.items():
            if not isinstance(task, dict):
                new_tasks[task_name] = task
                continue
            new_task = dict(task)
            inputs = task.get("inputs", [])
            new_inputs: list[str] = []
            for inp in inputs:
                if not isinstance(inp, str):
                    new_inputs.append(inp)
                    continue
                # 이미 v3 포맷이면 패스
                if inp.startswith(_V3_PREFIXES):
                    new_inputs.append(inp)
                    continue
                # source:<bare_id> 만 변환. task_<id> 등은 그대로.
                if inp.startswith("source:"):
                    bare_id = inp[len("source:"):]
                    new_inputs.append(f"source:{source_type}:{bare_id}")
                else:
                    new_inputs.append(inp)
            new_task["inputs"] = new_inputs
            new_tasks[task_name] = new_task
        new_config["tasks"] = new_tasks

    # passthrough_source_split_id / passthrough_source_dataset_id 는 필드명 자체에
    # type 정보가 있어 추가 변환 불필요.
    return new_config


def _rewrite_source_to_v2(config: Any) -> Any:
    """downgrade 용 — v3 prefix 제거 + schema_version 2."""
    if not isinstance(config, dict):
        return config

    new_config = dict(config)
    new_config["schema_version"] = 2

    tasks = new_config.get("tasks")
    if isinstance(tasks, dict):
        new_tasks: dict[str, Any] = {}
        for task_name, task in tasks.items():
            if not isinstance(task, dict):
                new_tasks[task_name] = task
                continue
            new_task = dict(task)
            inputs = task.get("inputs", [])
            new_inputs: list[str] = []
            for inp in inputs:
                if not isinstance(inp, str):
                    new_inputs.append(inp)
                    continue
                for prefix in _V3_PREFIXES:
                    if inp.startswith(prefix):
                        bare_id = inp[len(prefix):]
                        new_inputs.append(f"source:{bare_id}")
                        break
                else:
                    new_inputs.append(inp)
            new_task["inputs"] = new_inputs
            new_tasks[task_name] = new_task
        new_config["tasks"] = new_tasks

    return new_config


# ─────────────────────────────────────────────────────────────────────────────
# Upgrade
# ─────────────────────────────────────────────────────────────────────────────

def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # 1) pipeline_families 테이블 신규 생성
    # =========================================================================
    op.create_table(
        "pipeline_families",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "name", sa.String(255), nullable=False,
            comment="family 이름 — 사용자 즐겨찾기 폴더명",
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP, nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP, nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="uq_pipeline_families_name"),
    )

    # =========================================================================
    # 2) pipeline_versions 테이블 신규 생성 (FK 는 pipelines 가 아직 변형 전이라
    #    임시로 nullable 상태로 시작 — 데이터 이행 후 NOT NULL 로 전환)
    # =========================================================================
    op.create_table(
        "pipeline_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "pipeline_id", postgresql.UUID(as_uuid=False), nullable=True,
            comment="모 Pipeline (concept). 아래 데이터 이행 후 NOT NULL 전환",
        ),
        sa.Column(
            "version", sa.String(20), nullable=False,
            server_default=sa.text("'1.0'"),
        ),
        sa.Column(
            "config", postgresql.JSONB, nullable=False,
            comment=(
                "PipelineConfig JSONB 스냅샷 (schema_version=3, source 토큰 v3 포맷). "
                "생성 후 immutable"
            ),
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False,
            server_default=sa.text("TRUE"),
            comment="version 단위 soft delete (concept 의 is_active 와 독립)",
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

    # =========================================================================
    # 3) 기존 pipelines 행 읽어 메모리에 보관 (변형 전 스냅샷)
    # =========================================================================
    existing_rows = conn.execute(sa.text(
        "SELECT id, name, version, description, output_split_id, "
        "config, task_type, is_active, created_at, updated_at "
        "FROM pipelines"
    )).mappings().all()

    # name → 새 concept pipeline_id 매핑 (name 별 1개 concept)
    name_to_concept_id: dict[str, str] = {}
    for row in existing_rows:
        if row["name"] not in name_to_concept_id:
            name_to_concept_id[row["name"]] = str(uuid.uuid4())

    # =========================================================================
    # 4) 기존 pipelines 테이블을 잠시 다른 이름으로 비우기 위해
    #    제약·인덱스 제거 + 컬럼 재구성
    # =========================================================================

    # 4-1. 자식 FK 제거 (pipeline_runs / pipeline_automations 에서 pipelines 참조)
    op.drop_constraint(
        "fk_pipeline_executions_pipeline_id",
        "pipeline_runs", type_="foreignkey",
    )
    op.drop_constraint(
        "pipeline_automations_pipeline_id_fkey",
        "pipeline_automations", type_="foreignkey",
    )

    # 4-2. pipelines 의 인덱스 / unique constraint 제거
    op.drop_index("ix_pipelines_name_is_active", table_name="pipelines")
    op.drop_constraint(
        "uq_pipeline_name_version", "pipelines", type_="unique",
    )

    # 4-3. pipelines 에서 version / config 컬럼 제거
    op.drop_column("pipelines", "version")
    op.drop_column("pipelines", "config")

    # 4-4. pipelines 에 family_id 컬럼 추가 (NULL 허용)
    op.add_column(
        "pipelines",
        sa.Column(
            "family_id", postgresql.UUID(as_uuid=False), nullable=True,
            comment="즐겨찾기 폴더 — NULL 이면 미분류",
        ),
    )
    op.create_foreign_key(
        "fk_pipelines_family_id",
        "pipelines", "pipeline_families",
        ["family_id"], ["id"],
        ondelete="SET NULL",
    )

    # 4-5. pipelines 데이터 정리 — 기존 행 삭제 후 concept 행으로 재삽입
    #      (PK 가 같이 바뀌므로 DELETE → INSERT 가 가장 깔끔)
    op.execute("DELETE FROM pipelines")

    for name, concept_id in name_to_concept_id.items():
        # 같은 name 의 row 중 첫 행을 canonical 로 사용
        canonical = sorted(
            [r for r in existing_rows if r["name"] == name],
            key=lambda r: r["created_at"],
        )[0]
        any_active = any(
            r["is_active"] for r in existing_rows if r["name"] == name
        )
        conn.execute(
            sa.text(
                "INSERT INTO pipelines "
                "(id, family_id, name, description, task_type, output_split_id, "
                "is_active, created_at, updated_at) "
                "VALUES (:id, NULL, :name, :description, :task_type, "
                ":output_split_id, :is_active, :created_at, :updated_at)"
            ),
            {
                "id": concept_id,
                "name": name,
                "description": canonical["description"],
                "task_type": canonical["task_type"],
                "output_split_id": canonical["output_split_id"],
                "is_active": any_active,
                "created_at": canonical["created_at"],
                "updated_at": canonical["updated_at"],
            },
        )

    # 4-6. name 전역 UNIQUE constraint 신설
    op.create_unique_constraint(
        "uq_pipelines_name", "pipelines", ["name"],
    )
    op.create_index(
        "ix_pipelines_name_is_active", "pipelines", ["name", "is_active"],
    )

    # =========================================================================
    # 5) pipeline_versions 행 삽입
    #    id 를 기존 pipelines.id 로 보존 → 자식 FK 가 값 변경 없이 의미 전환
    # =========================================================================
    for row in existing_rows:
        rewritten = _rewrite_source_to_v3(row["config"], "dataset_split")
        conn.execute(
            sa.text(
                "INSERT INTO pipeline_versions "
                "(id, pipeline_id, version, config, is_active, "
                "created_at, updated_at) "
                "VALUES (:id, :pipeline_id, :version, CAST(:config AS jsonb), "
                ":is_active, :created_at, :updated_at)"
            ),
            {
                "id": row["id"],
                "pipeline_id": name_to_concept_id[row["name"]],
                "version": row["version"],
                "config": json.dumps(rewritten),
                "is_active": row["is_active"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    # 5-1. pipeline_versions FK / 제약 마무리
    op.alter_column("pipeline_versions", "pipeline_id", nullable=False)
    op.create_foreign_key(
        "fk_pipeline_versions_pipeline_id",
        "pipeline_versions", "pipelines",
        ["pipeline_id"], ["id"],
        ondelete="CASCADE",  # concept 삭제 시 모든 version 같이 정리
    )
    op.create_unique_constraint(
        "uq_pipeline_versions_pipeline_version",
        "pipeline_versions", ["pipeline_id", "version"],
    )
    op.create_index(
        "ix_pipeline_versions_pipeline_active",
        "pipeline_versions", ["pipeline_id", "is_active"],
    )

    # =========================================================================
    # 6) pipeline_runs.pipeline_id → pipeline_version_id rename
    #    값은 그대로 (pipeline_versions.id == 기존 pipelines.id 보존)
    # =========================================================================
    op.alter_column(
        "pipeline_runs", "pipeline_id",
        new_column_name="pipeline_version_id",
    )
    op.create_foreign_key(
        "fk_pipeline_runs_pipeline_version_id",
        "pipeline_runs", "pipeline_versions",
        ["pipeline_version_id"], ["id"],
        ondelete="RESTRICT",
    )

    # 6-1. transform_config 의 source 토큰 v3 로 rewrite
    runs = conn.execute(sa.text(
        "SELECT id, transform_config FROM pipeline_runs "
        "WHERE transform_config IS NOT NULL"
    )).mappings().all()
    for run in runs:
        rewritten = _rewrite_source_to_v3(run["transform_config"], "dataset_version")
        conn.execute(
            sa.text(
                "UPDATE pipeline_runs SET transform_config = CAST(:tc AS jsonb) "
                "WHERE id = :id"
            ),
            {"id": run["id"], "tc": json.dumps(rewritten)},
        )

    # =========================================================================
    # 7) pipeline_automations.pipeline_id → pipeline_version_id rename
    # =========================================================================
    op.alter_column(
        "pipeline_automations", "pipeline_id",
        new_column_name="pipeline_version_id",
    )
    op.create_foreign_key(
        "fk_pipeline_automations_pipeline_version_id",
        "pipeline_automations", "pipeline_versions",
        ["pipeline_version_id"], ["id"],
        ondelete="RESTRICT",
    )

    # 7-1. partial unique index 재생성 (이전: pipeline_id 기준 → 새: pipeline_version_id)
    op.execute("DROP INDEX IF EXISTS uq_pipeline_automation_active_pipeline")
    op.execute(
        "CREATE UNIQUE INDEX uq_pipeline_automation_active_version "
        "ON pipeline_automations (pipeline_version_id) WHERE is_active = TRUE"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Downgrade
# ─────────────────────────────────────────────────────────────────────────────

def downgrade() -> None:
    """v3 → v2 역방향. concept/version 합치기 + source prefix 제거."""
    conn = op.get_bind()

    # =========================================================================
    # 7r) pipeline_automations.pipeline_version_id → pipeline_id 복귀
    # =========================================================================
    op.execute("DROP INDEX IF EXISTS uq_pipeline_automation_active_version")
    op.drop_constraint(
        "fk_pipeline_automations_pipeline_version_id",
        "pipeline_automations", type_="foreignkey",
    )
    op.alter_column(
        "pipeline_automations", "pipeline_version_id",
        new_column_name="pipeline_id",
    )
    # FK 는 v1 시점 이름으로 복귀 (pipelines 가 아직 concept 테이블이라
    # FK 대상은 마지막에 다시 연결)

    # =========================================================================
    # 6r) pipeline_runs.pipeline_version_id → pipeline_id 복귀
    # =========================================================================
    op.drop_constraint(
        "fk_pipeline_runs_pipeline_version_id",
        "pipeline_runs", type_="foreignkey",
    )
    op.alter_column(
        "pipeline_runs", "pipeline_version_id",
        new_column_name="pipeline_id",
    )

    # 6-1r) transform_config v3 → v2
    runs = conn.execute(sa.text(
        "SELECT id, transform_config FROM pipeline_runs "
        "WHERE transform_config IS NOT NULL"
    )).mappings().all()
    for run in runs:
        rewritten = _rewrite_source_to_v2(run["transform_config"])
        conn.execute(
            sa.text(
                "UPDATE pipeline_runs SET transform_config = CAST(:tc AS jsonb) "
                "WHERE id = :id"
            ),
            {"id": run["id"], "tc": json.dumps(rewritten)},
        )

    # =========================================================================
    # 5r) pipelines (concept) 와 pipeline_versions 를 합쳐 v1 형태로 복원
    # =========================================================================
    # 사전: 현 pipelines 행 (concept) 백업
    concept_rows = conn.execute(sa.text(
        "SELECT id, name, description, task_type, output_split_id, "
        "is_active, created_at, updated_at FROM pipelines"
    )).mappings().all()

    version_rows = conn.execute(sa.text(
        "SELECT id, pipeline_id, version, config, is_active, "
        "created_at, updated_at FROM pipeline_versions"
    )).mappings().all()

    concept_by_id = {c["id"]: c for c in concept_rows}

    # pipelines 의 concept 데이터 비우기 (재삽입 위해)
    op.drop_index("ix_pipeline_versions_pipeline_active", table_name="pipeline_versions")
    op.drop_constraint(
        "uq_pipeline_versions_pipeline_version",
        "pipeline_versions", type_="unique",
    )
    op.drop_constraint(
        "fk_pipeline_versions_pipeline_id",
        "pipeline_versions", type_="foreignkey",
    )

    op.drop_index("ix_pipelines_name_is_active", table_name="pipelines")
    op.drop_constraint("uq_pipelines_name", "pipelines", type_="unique")
    op.drop_constraint(
        "fk_pipelines_family_id", "pipelines", type_="foreignkey",
    )
    op.drop_column("pipelines", "family_id")
    op.execute("DELETE FROM pipelines")

    # v1 컬럼 복귀: version / config
    op.add_column(
        "pipelines",
        sa.Column("version", sa.String(20), nullable=True),
    )
    op.add_column(
        "pipelines",
        sa.Column("config", postgresql.JSONB, nullable=True),
    )

    # 각 PipelineVersion → 1 pipelines 행으로 펼침
    for vr in version_rows:
        concept = concept_by_id[vr["pipeline_id"]]
        conn.execute(
            sa.text(
                "INSERT INTO pipelines "
                "(id, name, version, description, output_split_id, config, "
                "task_type, is_active, created_at, updated_at) "
                "VALUES (:id, :name, :version, :description, :output_split_id, "
                "CAST(:config AS jsonb), :task_type, :is_active, "
                ":created_at, :updated_at)"
            ),
            {
                "id": vr["id"],
                "name": concept["name"],
                "version": vr["version"],
                "description": concept["description"],
                "output_split_id": concept["output_split_id"],
                "config": json.dumps(vr["config"]),
                "task_type": concept["task_type"],
                "is_active": vr["is_active"],
                "created_at": vr["created_at"],
                "updated_at": vr["updated_at"],
            },
        )

    op.alter_column("pipelines", "version", nullable=False)
    op.alter_column("pipelines", "config", nullable=False)
    op.create_unique_constraint(
        "uq_pipeline_name_version", "pipelines", ["name", "version"],
    )
    op.create_index(
        "ix_pipelines_name_is_active", "pipelines", ["name", "is_active"],
    )

    # 자식 FK 재연결 (이름은 v1 시점)
    op.create_foreign_key(
        "fk_pipeline_executions_pipeline_id",
        "pipeline_runs", "pipelines",
        ["pipeline_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "pipeline_automations_pipeline_id_fkey",
        "pipeline_automations", "pipelines",
        ["pipeline_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pipeline_automation_active_pipeline "
        "ON pipeline_automations (pipeline_id) WHERE is_active = TRUE"
    )

    # =========================================================================
    # 2r/1r) pipeline_versions / pipeline_families DROP
    # =========================================================================
    op.drop_table("pipeline_versions")

    op.drop_table("pipeline_families")
