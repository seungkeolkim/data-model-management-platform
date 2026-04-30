"""
PipelineAutomation 서비스 (v7.11 — pipeline_version_id 단위로 격하).

PipelineVersion 과 1:0..1 관계의 runner 등록 CRUD 및 수동 재실행(rerun) 로직.
polling / triggering 스캐너 자체는 별도 챕터.

soft delete 를 따른다 — `DELETE` 는 row 를 지우지 않고 `is_active`
를 False + `deleted_at=NOW()` 로 세팅. partial unique index 덕에 같은
pipeline_version 에 새 automation 을 다시 등록할 수 있다.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.all_models import (
    DatasetSplit,
    DatasetVersion,
    Pipeline,
    PipelineAutomation,
    PipelineRun,
    PipelineVersion,
)
from app.schemas.pipeline import (
    PipelineAutomationRerunRequest,
    PipelineAutomationUpsertRequest,
    PipelineSubmitResponse,
)
from lib.pipeline.config import PipelineConfig

logger = structlog.get_logger(__name__)


class PipelineAutomationService:
    """자동화 등록 / 업데이트 / soft delete / 수동 재실행 — version 단위."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # 조회
    # ─────────────────────────────────────────────────────────────────────────

    async def get_active_by_pipeline_version(
        self, pipeline_version_id: str,
    ) -> PipelineAutomation | None:
        """PipelineVersion 의 현재 활성 자동화 (is_active=True). 없으면 None."""
        result = await self.db.execute(
            select(PipelineAutomation)
            .where(
                PipelineAutomation.pipeline_version_id == pipeline_version_id,
                PipelineAutomation.is_active == True,  # noqa: E712
            )
        )
        return result.scalars().first()

    async def get_by_id(self, automation_id: str) -> PipelineAutomation | None:
        result = await self.db.execute(
            select(PipelineAutomation).where(PipelineAutomation.id == automation_id)
        )
        return result.scalars().first()

    async def list_all_active(self) -> list[PipelineAutomation]:
        """활성 자동화 전체 (Automation 관리 페이지 좌측 목록)."""
        result = await self.db.execute(
            select(PipelineAutomation)
            .where(PipelineAutomation.is_active == True)  # noqa: E712
            .order_by(PipelineAutomation.created_at.desc())
        )
        return list(result.scalars().all())

    # ─────────────────────────────────────────────────────────────────────────
    # upsert (register / update)
    # ─────────────────────────────────────────────────────────────────────────

    async def upsert_automation(
        self,
        pipeline_version_id: str,
        request: PipelineAutomationUpsertRequest,
    ) -> PipelineAutomation:
        """
        자동화 등록 또는 갱신. 해당 PipelineVersion 에 active automation 이 있으면
        갱신, 없으면 신규 INSERT.

        PipelineVersion 또는 모 Pipeline 이 비활성이면 등록 불가.
        """
        pipeline_version = await self._get_pipeline_version_strict(pipeline_version_id)
        if not pipeline_version.is_active:
            raise ValueError(
                "비활성 PipelineVersion 에는 automation 을 등록할 수 없습니다."
            )
        if pipeline_version.pipeline is None or not pipeline_version.pipeline.is_active:
            raise ValueError(
                "비활성 Pipeline 의 version 에는 automation 을 등록할 수 없습니다."
            )

        existing = await self.get_active_by_pipeline_version(pipeline_version_id)
        if existing is not None:
            existing.status = request.status
            existing.mode = request.mode
            existing.poll_interval = request.poll_interval
            if request.status != "error":
                existing.error_reason = None
            await self.db.flush()
            logger.info(
                "Automation 갱신", automation_id=existing.id,
                pipeline_version_id=pipeline_version_id, status=request.status,
            )
            return existing

        automation = PipelineAutomation(
            id=str(uuid.uuid4()),
            pipeline_version_id=pipeline_version_id,
            status=request.status,
            mode=request.mode,
            poll_interval=request.poll_interval,
            error_reason=None,
            last_seen_input_versions=None,
            is_active=True,
            deleted_at=None,
        )
        self.db.add(automation)
        await self.db.flush()
        logger.info(
            "Automation 신규 등록", automation_id=automation.id,
            pipeline_version_id=pipeline_version_id, status=request.status,
        )
        return automation

    # ─────────────────────────────────────────────────────────────────────────
    # soft delete
    # ─────────────────────────────────────────────────────────────────────────

    async def soft_delete(self, automation_id: str) -> PipelineAutomation | None:
        """자동화 soft delete — row 유지, `is_active=False` + `deleted_at=NOW()`."""
        automation = await self.get_by_id(automation_id)
        if automation is None:
            return None
        if not automation.is_active:
            return automation  # idempotent
        automation.is_active = False
        automation.deleted_at = datetime.utcnow()
        await self.db.flush()
        logger.info(
            "Automation soft delete", automation_id=automation.id,
            pipeline_version_id=automation.pipeline_version_id,
        )
        return automation

    # ─────────────────────────────────────────────────────────────────────────
    # reassign (다른 PipelineVersion 으로 이전)
    # ─────────────────────────────────────────────────────────────────────────

    async def reassign_pipeline_version(
        self, automation_id: str, new_pipeline_version_id: str,
    ) -> PipelineAutomation | None:
        """
        자동화가 가리키는 PipelineVersion 을 다른 PipelineVersion 으로 이전.
        v1.0 → v2.0 승격 시 자동화 설정 (mode / poll_interval) 을 유지하며
        대상만 변경.
        """
        automation = await self.get_by_id(automation_id)
        if automation is None:
            return None
        new_version = await self._get_pipeline_version_strict(new_pipeline_version_id)
        if not new_version.is_active:
            raise ValueError("reassign 대상 PipelineVersion 이 비활성 상태입니다.")
        if new_version.pipeline is None or not new_version.pipeline.is_active:
            raise ValueError("reassign 대상의 모 Pipeline 이 비활성 상태입니다.")
        target_existing = await self.get_active_by_pipeline_version(
            new_pipeline_version_id
        )
        if target_existing is not None and target_existing.id != automation.id:
            raise ValueError(
                f"대상 PipelineVersion ({new_pipeline_version_id}) 에 이미 활성 "
                "automation 이 있습니다. 먼저 정리 후 재시도하세요."
            )
        automation.pipeline_version_id = new_pipeline_version_id
        if automation.error_reason == "PIPELINE_DELETED":
            automation.error_reason = None
            automation.status = "stopped"
        await self.db.flush()
        logger.info(
            "Automation reassign", automation_id=automation.id,
            new_pipeline_version_id=new_pipeline_version_id,
        )
        return automation

    # ─────────────────────────────────────────────────────────────────────────
    # 수동 재실행
    # ─────────────────────────────────────────────────────────────────────────

    async def trigger_manual_rerun(
        self,
        automation_id: str,
        request: PipelineAutomationRerunRequest,
    ) -> PipelineSubmitResponse:
        """
        수동 재실행 — "이 automation 을 지금 즉시 실행".

        mode:
          - if_delta: `last_seen_input_versions` vs 현재 최신 input versions 비교.
                      delta 없으면 SKIPPED_NO_DELTA 이력만 남김
          - force_latest: delta 무시. 무조건 최신 version 으로 dispatch
        """
        automation = await self.get_by_id(automation_id)
        if automation is None:
            raise ValueError(f"Automation not found: {automation_id}")
        if not automation.is_active:
            raise ValueError("soft-deleted 자동화는 재실행할 수 없습니다.")
        if automation.status == "error":
            raise ValueError(
                f"Automation 이 error 상태입니다 (reason={automation.error_reason}). "
                "상태를 먼저 해소하세요."
            )

        version_result = await self.db.execute(
            select(PipelineVersion)
            .options(
                selectinload(PipelineVersion.pipeline)
                .selectinload(Pipeline.output_split)
                .selectinload(DatasetSplit.group),
            )
            .where(PipelineVersion.id == automation.pipeline_version_id)
        )
        pipeline_version = version_result.scalars().first()
        if pipeline_version is None or not pipeline_version.is_active:
            raise ValueError(
                "Automation 의 대상 PipelineVersion 이 없거나 비활성 상태입니다."
            )
        pipeline = pipeline_version.pipeline
        if pipeline is None or not pipeline.is_active:
            raise ValueError(
                "Automation 의 모 Pipeline 이 비활성 상태입니다."
            )

        config = PipelineConfig(**pipeline_version.config)
        latest_versions = await self._collect_latest_input_versions(config)

        last_seen = automation.last_seen_input_versions or {}
        has_delta = latest_versions != last_seen
        if request.mode == "if_delta" and not has_delta:
            skip_run = PipelineRun(
                id=str(uuid.uuid4()),
                pipeline_version_id=pipeline_version.id,
                automation_id=automation.id,
                output_dataset_id=await self._sentinel_dataset_id(pipeline),
                transform_config=pipeline_version.config,
                resolved_input_versions=latest_versions,
                trigger_kind="automation_manual_rerun",
                automation_trigger_source="manual_rerun",
                status="SKIPPED_NO_DELTA",
                error_message="상류 입력 버전 변경 없음 (if_delta 모드 skip)",
            )
            self.db.add(skip_run)
            await self.db.flush()
            logger.info(
                "Automation manual_rerun skipped — no delta",
                automation_id=automation.id,
                pipeline_version_id=pipeline_version.id,
                latest_versions=latest_versions,
            )
            return PipelineSubmitResponse(
                execution_id=skip_run.id,
                celery_task_id=None,
                message="상류 입력 버전 변경 없음 — SKIPPED_NO_DELTA 레코드만 남겼습니다.",
            )

        from app.services.pipeline_service import PipelineService

        service = PipelineService(self.db)
        response = await service.submit_run_from_pipeline_version(
            pipeline_version.id, latest_versions,
        )

        run_result = await self.db.execute(
            select(PipelineRun).where(PipelineRun.id == response.execution_id)
        )
        run = run_result.scalars().first()
        if run is not None:
            run.trigger_kind = "automation_manual_rerun"
            run.automation_trigger_source = "manual_rerun"
            run.automation_id = automation.id
            await self.db.flush()

        automation.last_seen_input_versions = latest_versions
        await self.db.flush()
        return response

    # ─────────────────────────────────────────────────────────────────────────
    # 내부 헬퍼
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_pipeline_version_strict(
        self, pipeline_version_id: str,
    ) -> PipelineVersion:
        result = await self.db.execute(
            select(PipelineVersion)
            .options(selectinload(PipelineVersion.pipeline))
            .where(PipelineVersion.id == pipeline_version_id)
        )
        pipeline_version = result.scalars().first()
        if pipeline_version is None:
            raise ValueError(f"PipelineVersion not found: {pipeline_version_id}")
        return pipeline_version

    async def _collect_latest_input_versions(
        self, config: PipelineConfig,
    ) -> dict[str, str]:
        """config 가 참조하는 source split 들의 현재 최신 READY version 수집."""
        split_ids = set(config.get_all_source_split_ids())
        if not split_ids:
            return {}
        latest_result = await self.db.execute(
            select(DatasetVersion)
            .where(
                DatasetVersion.split_id.in_(split_ids),
                DatasetVersion.status == "READY",
            )
            .order_by(DatasetVersion.split_id, DatasetVersion.created_at.desc())
        )
        latest_by_split: dict[str, str] = {}
        for dv in latest_result.scalars().all():
            if dv.split_id not in latest_by_split:
                latest_by_split[dv.split_id] = dv.version
        return latest_by_split

    async def _sentinel_dataset_id(self, pipeline: Pipeline) -> str:
        """
        SKIPPED_NO_DELTA run 도 `output_dataset_id NOT NULL` 제약을 받으므로 대체 값이
        필요. pipeline 의 output_split 에서 가장 최근 DatasetVersion 을 재사용.
        """
        latest = await self.db.execute(
            select(DatasetVersion)
            .where(DatasetVersion.split_id == pipeline.output_split_id)
            .order_by(DatasetVersion.created_at.desc())
            .limit(1)
        )
        dataset = latest.scalars().first()
        if dataset is not None:
            return dataset.id
        placeholder = DatasetVersion(
            id=str(uuid.uuid4()),
            split_id=pipeline.output_split_id,
            version="0.0",
            annotation_format="NONE",
            storage_uri="(automation_skip_placeholder)",
            status="ERROR",
            metadata_={"placeholder": True, "reason": "automation_skip_no_delta"},
        )
        self.db.add(placeholder)
        await self.db.flush()
        return placeholder.id
