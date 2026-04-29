"""
SQLAlchemy ORM 모델 정의

모든 테이블을 한 파일에 정의하여 Alembic이 자동으로 감지하도록 함.
실제 비즈니스 로직에서는 각 도메인별 import 사용.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# =============================================================================
# 1차 — 데이터셋 관리
# =============================================================================

class DatasetGroup(Base):
    """
    논리적 데이터셋 묶음.
    같은 이름의 데이터셋이 여러 split/version으로 존재할 때의 공통 메타정보.
    """
    __tablename__ = "dataset_groups"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    dataset_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="RAW | SOURCE | PROCESSED | FUSION"
    )
    annotation_format: Mapped[str] = mapped_column(
        String(30), nullable=False, default="NONE",
        comment="COCO | YOLO | ATTR_JSON | CLS_MANIFEST | CUSTOM | NONE"
    )
    task_types: Mapped[dict | list | None] = mapped_column(
        JSONB, nullable=True,
        comment='["DETECTION","SEGMENTATION","CLASSIFICATION","ZERO_SHOT"] 중 1개 원소 리스트'
    )
    modality: Mapped[str] = mapped_column(
        String(30), nullable=False, default="RGB",
        comment="RGB | THERMAL | DEPTH | MULTISPECTRAL"
    )
    source_origin: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # classification 전용: 그룹 단위 head/class 계약 (SSOT).
    # 예시: {"heads":[{"name":"hardhat_wear","multi_label":false,
    #                  "classes":["no_helmet","helmet"]}, ...]}
    # detection 등 다른 task 그룹에서는 NULL.
    head_schema: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="Classification 전용. head별 name/multi_label/classes 순서. 학습 output index의 SSOT"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now,
        onupdate=_now, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=False), nullable=True,
        comment="소프트 삭제 시각. NULL이면 활성 상태"
    )

    # Relationships
    # v7.9 (핸드오프 025): split → version 2단 계층.
    splits: Mapped[list[DatasetSplit]] = relationship(
        "DatasetSplit", back_populates="group", lazy="select",
        cascade="all, delete-orphan",
    )

    @property
    def datasets(self) -> list[DatasetVersion]:
        """
        하위 호환 proxy — 기존 group.datasets 호출 코드와 호환.
        모든 split 의 모든 version 을 flat list 로 반환한다.

        association_proxy("splits", "versions") 는 collection-of-collections 패턴에서
        중첩 리스트를 돌려주어 Pydantic 직렬화가 깨지므로 명시적 property 로 flatten.
        쿼리(조건절) 에는 쓰지 않는다 — 서비스 계층은 splits/versions 를 직접 JOIN.
        """
        flat: list[DatasetVersion] = []
        for split_obj in self.splits:
            flat.extend(split_obj.versions)
        return flat


class DatasetSplit(Base):
    """
    DatasetGroup 아래의 정적 split 슬롯 (TRAIN / VAL / TEST / NONE).
    v7.9 신규 — 핸드오프 025.

    split 은 Group 내에서 유일하며 한 번 생성되면 재사용된다. 버전이 쌓여도 이 행은 변하지 않는다.
    Pipeline / automation 이 "특정 group 의 TRAIN split 최신 버전" 을 FK 무결성 하에 참조하기 위한 레이어.
    """
    __tablename__ = "dataset_splits"
    __table_args__ = (
        UniqueConstraint("group_id", "split", name="uq_dataset_split_group_split"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    group_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_groups.id", ondelete="CASCADE"), nullable=False
    )
    split: Mapped[str] = mapped_column(
        String(10), nullable=False, default="NONE",
        comment="TRAIN | VAL | TEST | NONE"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )

    # Relationships
    group: Mapped[DatasetGroup] = relationship("DatasetGroup", back_populates="splits")
    versions: Mapped[list[DatasetVersion]] = relationship(
        "DatasetVersion", back_populates="split_slot", lazy="select",
        cascade="all, delete-orphan",
    )


class DatasetVersion(Base):
    """
    실제 데이터셋의 동적 단위. 한 DatasetSplit 아래에 여러 version 이 쌓인다.
    v7.9 — 기존 `Dataset` 을 rename. DB 테이블명도 `datasets` → `dataset_versions` 로 변경.

    (split_id, version) 유니크. version 은 `{major}.{minor}` 문자열.
    """
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("split_id", "version", name="uq_dataset_versions_split_version"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    split_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_splits.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False, comment="{major}.{minor} 형식")
    annotation_format: Mapped[str | None] = mapped_column(
        String(30), nullable=True,
        comment="group 기본값 상속, version별 override 가능"
    )
    storage_uri: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="NAS 상대경로: processed/coco_aug/train/v1.0.0"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING",
        comment="PENDING | PROCESSING | READY | ERROR"
    )
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    class_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annotation_files: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
        comment='어노테이션 파일명 목록. 예: ["instances_train.json"]. NULL이면 레거시 annotation.json'
    )
    annotation_meta_file: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="어노테이션 메타 파일명 (예: data.yaml). YOLO 등 클래스 매핑이 별도 파일인 포맷용"
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True,
        comment="EDA 결과, 클래스 분포 등"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now,
        onupdate=_now, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=False), nullable=True,
        comment="소프트 삭제 시각. NULL이면 활성 상태"
    )

    # Relationships
    # split_slot — 정적 DatasetSplit 엔티티 (DB 측 FK = split_id). ORM 관계 이름을
    # "split_slot" 으로 둔 이유는 기존 코드 / Pydantic 스키마가 `version.split` 을
    # '문자열 split 이름' 으로 쓰고 있기 때문. 충돌을 피하기 위해 relationship 이름은
    # split_slot 으로, 문자열 노출은 아래 association_proxy 로 분리했다.
    split_slot: Mapped[DatasetSplit] = relationship(
        "DatasetSplit", back_populates="versions",
    )
    # 기존 Dataset.split (문자열) 사용 코드와 호환. DatasetSplit.split 컬럼을 투명 노출.
    split: AssociationProxy[str] = association_proxy("split_slot", "split")
    # 기존 Dataset.group / .group_id 사용 코드와 호환.
    group: AssociationProxy[DatasetGroup] = association_proxy("split_slot", "group")
    group_id: AssociationProxy[str] = association_proxy("split_slot", "group_id")

    lineage_as_parent: Mapped[list[DatasetLineage]] = relationship(
        "DatasetLineage", foreign_keys="DatasetLineage.parent_id", back_populates="parent"
    )
    lineage_as_child: Mapped[list[DatasetLineage]] = relationship(
        "DatasetLineage", foreign_keys="DatasetLineage.child_id", back_populates="child"
    )
    # v7.10 (핸드오프 027 §12): PipelineExecution → PipelineRun rename.
    pipeline_runs: Mapped[list[PipelineRun]] = relationship(
        "PipelineRun", back_populates="output_dataset"
    )

    @property
    def pipeline_run_id(self) -> str | None:
        """이 데이터셋을 생성한 파이프라인 실행 (PipelineRun) ID — 있으면 첫 번째."""
        if self.pipeline_runs:
            return self.pipeline_runs[0].id
        return None


class DatasetLineage(Base):
    """dataset_versions 단위 부모-자식 lineage 엣지. 테이블 이름은 역사적 호환을 위해 유지."""
    __tablename__ = "dataset_lineage"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    parent_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    child_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    transform_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="실행된 manipulator 구성 스냅샷"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )

    # Relationships
    parent: Mapped[DatasetVersion] = relationship("DatasetVersion", foreign_keys=[parent_id])
    child: Mapped[DatasetVersion] = relationship("DatasetVersion", foreign_keys=[child_id])


class Manipulator(Base):
    """사전 등록된 가공 함수 목록. GUI 동적 폼 생성의 기준."""
    __tablename__ = "manipulators"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="ANNOTATION_FILTER | IMAGE_FILTER | AUGMENT | FORMAT_CONVERT | MERGE | SAMPLE | REMAP"
    )
    scope: Mapped[list | None] = mapped_column(
        JSONB, nullable=False,
        comment='["PER_SOURCE"] | ["POST_MERGE"] | ["PER_SOURCE","POST_MERGE"]'
    )
    compatible_task_types: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
        comment='["DETECTION", ...]'
    )
    compatible_annotation_fmts: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
        comment='["COCO", "YOLO", ...]'
    )
    output_annotation_fmt: Mapped[str | None] = mapped_column(
        String(30), nullable=True,
        comment="format_convert류만 해당, 나머지 NULL"
    )
    params_schema: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="GUI 동적 폼 생성용 파라미터 스펙"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE",
        comment="ACTIVE | EXPERIMENTAL | DEPRECATED"
    )
    version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )


class PipelineFamily(Base):
    """
    Pipeline 의 즐겨찾기 폴더 (v7.11 신규 — feature/pipeline-family-and-version).

    Pipeline 들이 자유롭게 들고 날 수 있는 느슨한 묶음. DatasetGroup 처럼
    구조적 강제력은 없고, 사용자가 "이 family 에 묶어보고 싶다" 는 의도만
    담는다. Pipeline.family_id 는 NULL 허용 — 미분류 상태도 정상.
    """
    __tablename__ = "pipeline_families"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True,
        comment="family 이름 — 전역 UNIQUE",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(
        String(7), nullable=False,
        comment="Family 시각 구분 색 (`#RRGGBB`). 신규 생성 시 자동 할당, 수정 가능.",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now,
        onupdate=_now, server_default=func.now()
    )

    pipelines: Mapped[list[Pipeline]] = relationship(
        "Pipeline", back_populates="family",
    )


class Pipeline(Base):
    """
    Pipeline 의 개념 정체성 (v7.11 — feature/pipeline-family-and-version).

    "이 파이프라인이 무엇을 하는가" 의 단일 정체성. config / version 은
    하위 PipelineVersion 행으로 분리됨. output_split_id / task_type 은
    개념 레벨 고정 — 변경 시엔 다른 Pipeline 으로 만들어야 함.

    `name` 은 전역 UNIQUE (사용자 결정). family 간 자유 이동을 허용하기 때문에
    family 와 무관한 식별자가 됨.
    """
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    family_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("pipeline_families.id", ondelete="SET NULL"),
        nullable=True,
        comment="즐겨찾기 폴더. NULL 이면 미분류",
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True,
        comment="개념 이름. 전역 UNIQUE",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_split_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("dataset_splits.id", ondelete="RESTRICT"),
        nullable=False,
        comment="output 은 항상 단일 DatasetSplit, 개념 레벨 고정",
    )
    task_type: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="DETECTION | CLASSIFICATION | ... — 개념 레벨 고정",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="개념 단위 soft delete. False 면 모든 version 의 새 run / automation 차단",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now,
        onupdate=_now, server_default=func.now()
    )

    family: Mapped[PipelineFamily | None] = relationship(
        "PipelineFamily", back_populates="pipelines",
    )
    output_split: Mapped[DatasetSplit] = relationship("DatasetSplit")
    versions: Mapped[list[PipelineVersion]] = relationship(
        "PipelineVersion", back_populates="pipeline",
        cascade="all, delete-orphan",
        order_by="PipelineVersion.created_at.desc()",
    )


class PipelineVersion(Base):
    """
    Pipeline 의 한 버전 인스턴스 (v7.11 신규).

    `config` 는 생성 후 immutable (§6-1 유지). 같은 Pipeline 안에서 version 이
    누적된다. 다른 Pipeline 으로 이동 불가 — pipeline_id FK NOT NULL + RESTRICT.
    """
    __tablename__ = "pipeline_versions"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_id", "version",
            name="uq_pipeline_versions_pipeline_version",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    pipeline_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0",
        comment="{major}.{minor} — 사용자 명시로만 major++ (hash 판정 없음)",
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        comment=(
            "PipelineConfig JSONB 스냅샷 (schema_version=3, source 토큰 v3 포맷). "
            "생성 후 immutable"
        ),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="version 단위 soft delete (Pipeline 의 is_active 와 독립)",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now,
        onupdate=_now, server_default=func.now()
    )

    pipeline: Mapped[Pipeline] = relationship("Pipeline", back_populates="versions")
    runs: Mapped[list[PipelineRun]] = relationship(
        "PipelineRun", back_populates="pipeline_version",
    )
    # PipelineVersion : Automation = 1:0..1 (partial unique index)
    automation: Mapped[PipelineAutomation | None] = relationship(
        "PipelineAutomation", back_populates="pipeline_version",
        primaryjoin=(
            "and_(PipelineVersion.id == PipelineAutomation.pipeline_version_id, "
            "PipelineAutomation.is_active == True)"
        ),
        uselist=False, viewonly=True,
    )


class PipelineAutomation(Base):
    """
    PipelineVersion 과 1:0..1 관계의 runner 등록 (v7.11 — version 레벨로 격상).

    "Automation 은 family 가 아니라 특정 version 을 가리킨다" 결정 (§3-3) 유지.
    pipeline_version_id 단위로 partial unique 제약. soft delete 패턴 동일.
    """
    __tablename__ = "pipeline_automations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    pipeline_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("pipeline_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="stopped",
        comment="stopped | active | error",
    )
    mode: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="polling | triggering | NULL (stopped)",
    )
    poll_interval: Mapped[str | None] = mapped_column(
        String(10), nullable=True,
        comment="10m | 1h | 6h | 24h | NULL (polling 외)",
    )
    error_reason: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="CYCLE_DETECTED | PIPELINE_DELETED | INPUT_GROUP_NOT_FOUND 등",
    )
    last_seen_input_versions: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="{split_id: version}. 자동 실행 성공 시 갱신. delta 판정 기준",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="soft delete — §12-3",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=False), nullable=True,
        comment="soft delete 시각",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now,
        onupdate=_now, server_default=func.now()
    )

    # Relationships
    pipeline_version: Mapped[PipelineVersion] = relationship(
        "PipelineVersion", back_populates="automation",
    )


class PipelineRun(Base):
    """
    파이프라인 실행 이력 및 진행 상태 (v7.10 — 기존 `PipelineExecution` rename).

    생성 후 immutable: 상태 전이(PENDING → RUNNING → DONE/FAILED)는 허용하되 실행
    결과 필드 (`output_dataset_id`, `transform_config`, `started_at`, `finished_at`)
    덮어쓰기 금지. 027 §6-3.
    """
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    pipeline_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("pipeline_versions.id", ondelete="RESTRICT"),
        nullable=False,
        comment="소속 PipelineVersion (NOT NULL). v7.11 — Pipeline → PipelineVersion 으로 격하",
    )
    automation_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("pipeline_automations.id", ondelete="RESTRICT"),
        nullable=True,
        comment="automation 경로 전용. manual_from_editor 시 NULL",
    )
    output_dataset_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    transform_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment=(
            "실행 시점 전체 PipelineConfig 스냅파트 (resolved 포함). "
            "Pipeline.config 가 soft-deleted/손상돼도 과거 run 해석 가능 (027 §2-2)"
        ),
    )
    resolved_input_versions: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="{split_id: version} — run 제출 시점의 input 버전 해석",
    )
    trigger_kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="manual_from_editor",
        server_default="manual_from_editor",
        comment="manual_from_editor | automation_auto | automation_manual_rerun (§9-7)",
    )
    automation_trigger_source: Mapped[str | None] = mapped_column(
        String(40), nullable=True,
        comment="polling | triggering | manual_rerun | NULL (manual_from_editor 시)",
    )
    automation_batch_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True,
        comment="같은 automation tick 에서 토폴로지 순서로 함께 실행된 run 묶음 ID",
    )
    pipeline_image_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="향후 pipeline.png 경로 저장용 (027 §2-2)",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING",
        comment="PENDING | RUNNING | DONE | FAILED | SKIPPED_NO_DELTA | SKIPPED_UPSTREAM_FAILED"
    )
    current_stage: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="annotation_processing | image_writing"
    )
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task_progress: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="DAG 태스크별 진행 상태. {task_name: {status, started_at, finished_at, ...}}"
    )
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )

    # Relationships
    pipeline_version: Mapped[PipelineVersion] = relationship(
        "PipelineVersion", back_populates="runs",
    )
    automation: Mapped[PipelineAutomation | None] = relationship("PipelineAutomation")
    output_dataset: Mapped[DatasetVersion] = relationship("DatasetVersion", back_populates="pipeline_runs")


# =============================================================================
# 2차 대비 — 모델 학습 관리 (Phase 0에서 빈 테이블로 생성)
# =============================================================================

class Objective(Base):
    """학습 목적 (Detection, Segmentation 등)."""
    __tablename__ = "objectives"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )

    recipes: Mapped[list[Recipe]] = relationship("Recipe", back_populates="objective")


class Recipe(Base):
    """Model + 학습 Config (데이터 제외)."""
    __tablename__ = "recipes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    objective_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("objectives.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="ULTRALYTICS | MMYOLO | CUSTOM"
    )
    base_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="epochs, lr, optimizer 등 학습 기본 설정"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )

    objective: Mapped[Objective] = relationship("Objective", back_populates="recipes")
    solutions: Mapped[list[Solution]] = relationship("Solution", back_populates="recipe")


class Solution(Base):
    """recipe + dataset 조합."""
    __tablename__ = "solutions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipe_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False
    )
    train_dataset_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    val_dataset_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    test_dataset_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )

    recipe: Mapped[Recipe] = relationship("Recipe", back_populates="solutions")
    versions: Mapped[list[SolutionVersion]] = relationship("SolutionVersion", back_populates="solution")


class SolutionVersion(Base):
    """실제 학습 단위."""
    __tablename__ = "solution_versions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    solution_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("solutions.id", ondelete="CASCADE"), nullable=False
    )
    override_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="recipe base_config에서 변경된 값만"
    )
    gpu_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING",
        comment="PENDING | QUEUED | RUNNING | DONE | FAILED"
    )
    mlflow_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )

    solution: Mapped[Solution] = relationship("Solution", back_populates="versions")
    training_jobs: Mapped[list[TrainingJob]] = relationship("TrainingJob", back_populates="solution_version")


class TrainingJob(Base):
    """실제 학습 실행 이력."""
    __tablename__ = "training_jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("solution_versions.id", ondelete="CASCADE"), nullable=False
    )
    container_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Docker container ID (2차) / K8S Pod name (3차)"
    )
    gpu_ids: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
        comment="할당된 GPU 번호 목록"
    )
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=False), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="best/last epoch 성능 지표"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, default=_now, server_default=func.now()
    )

    solution_version: Mapped[SolutionVersion] = relationship("SolutionVersion", back_populates="training_jobs")
