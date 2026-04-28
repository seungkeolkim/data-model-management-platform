"""
PipelineAutomation 서비스 (v7.10 — 핸드오프 027 §2-3 / §12-3).

Pipeline 과 1:0..1 관계의 runner 등록 CRUD 및 수동 재실행(rerun) 로직. polling /
triggering 스캐너 자체는 별도 챕터 (§5 항목 16 "Automation 실구현") 에서 다룬다.

본 서비스는 §12-3 soft delete 를 따른다 — `DELETE` 는 row 를 지우지 않고 `is_active`
를 False + `deleted_at=NOW()` 로 세팅. partial unique index 덕에 같은 pipeline 에
새 automation 을 다시 등록할 수 있다.
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
)
from app.schemas.pipeline import (
    PipelineAutomationRerunRequest,
    PipelineAutomationUpsertRequest,
    PipelineSubmitResponse,
)
from lib.pipeline.config import PipelineConfig

logger = structlog.get_logger(__name__)


class PipelineAutomationService:
    """자동화 등록 / 업데이트 / soft delete / 수동 재실행."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # 조회
    # ─────────────────────────────────────────────────────────────────────────

    async def get_active_by_pipeline(
        self, pipeline_id: str,
    ) -> PipelineAutomation | None:
        """Pipeline 의 현재 활성 자동화 (is_active=True) 반환. 없으면 None."""
        result = await self.db.execute(
            select(PipelineAutomation)
            .where(
                PipelineAutomation.pipeline_id == pipeline_id,
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
        pipeline_id: str,
        request: PipelineAutomationUpsertRequest,
    ) -> PipelineAutomation:
        """
        자동화 등록 또는 갱신. 해당 Pipeline 에 active automation 이 있으면 갱신,
        없으면 신규 INSERT.

        Pipeline.is_active=FALSE (soft-deleted) 에는 automation 등록 불가.
        """
        pipeline = await self._get_pipeline_strict(pipeline_id)
        if not pipeline.is_active:
            raise ValueError(
                "is_active=FALSE 인 Pipeline 에는 automation 을 등록할 수 없습니다."
            )

        existing = await self.get_active_by_pipeline(pipeline_id)
        if existing is not None:
            existing.status = request.status
            existing.mode = request.mode
            existing.poll_interval = request.poll_interval
            # status 가 stopped 로 가거나 active 로 복귀할 때 error_reason 은 초기화
            if request.status != "error":
                existing.error_reason = None
            await self.db.flush()
            logger.info(
                "Automation 갱신", automation_id=existing.id,
                pipeline_id=pipeline_id, status=request.status,
            )
            return existing

        automation = PipelineAutomation(
            id=str(uuid.uuid4()),
            pipeline_id=pipeline_id,
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
            pipeline_id=pipeline_id, status=request.status,
        )
        return automation

    # ─────────────────────────────────────────────────────────────────────────
    # soft delete (§12-3)
    # ─────────────────────────────────────────────────────────────────────────

    async def soft_delete(self, automation_id: str) -> PipelineAutomation | None:
        """
        자동화 soft delete — row 유지, `is_active=False` + `deleted_at=NOW()`.

        FK 제약 유지 덕에 과거 PipelineRun.automation_id 참조는 영원히 유효.
        """
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
            pipeline_id=automation.pipeline_id,
        )
        return automation

    # ─────────────────────────────────────────────────────────────────────────
    # reassign (§6-4 (a))
    # ─────────────────────────────────────────────────────────────────────────

    async def reassign_pipeline(
        self, automation_id: str, new_pipeline_id: str,
    ) -> PipelineAutomation | None:
        """
        자동화가 가리키는 Pipeline 을 다른 Pipeline 으로 이전. v1 → v2 승격 후에도
        자동화 설정 (mode / poll_interval) 을 유지하면서 대상만 바꾸는 용도 (§6-4).
        """
        automation = await self.get_by_id(automation_id)
        if automation is None:
            return None
        new_pipeline = await self._get_pipeline_strict(new_pipeline_id)
        if not new_pipeline.is_active:
            raise ValueError("reassign 대상 Pipeline 이 비활성 상태입니다.")
        # 다른 Pipeline 에 이미 active 가 있으면 충돌 (partial unique)
        target_existing = await self.get_active_by_pipeline(new_pipeline_id)
        if target_existing is not None and target_existing.id != automation.id:
            raise ValueError(
                f"대상 Pipeline ({new_pipeline_id}) 에 이미 활성 automation 이 있습니다. "
                "먼저 해당 automation 을 삭제하거나 현재 automation 을 삭제하고 "
                "해당 automation 을 갱신하세요."
            )
        automation.pipeline_id = new_pipeline_id
        # reassign 시 error_reason 은 해소된 것으로 간주 (§6-4 (a))
        if automation.error_reason == "PIPELINE_DELETED":
            automation.error_reason = None
            automation.status = "stopped"
        await self.db.flush()
        logger.info(
            "Automation reassign", automation_id=automation.id,
            new_pipeline_id=new_pipeline_id,
        )
        return automation

    # ─────────────────────────────────────────────────────────────────────────
    # 수동 재실행 (026 §5-2a / 027 §4-4)
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
                      delta 없으면 SKIPPED_NO_DELTA 이력 레코드를 남기고 dispatch 안 함
                      (026 §5-2a, 027 §4-4)
          - force_latest: delta 무시. 무조건 최신 version 으로 dispatch

        자동화 경로이므로 `trigger_kind='automation_manual_rerun'`,
        `automation_trigger_source='manual_rerun'`. Pipeline.config 기반으로 submit.
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

        pipeline_result = await self.db.execute(
            select(Pipeline)
            .options(
                selectinload(Pipeline.output_split).selectinload(DatasetSplit.group),
            )
            .where(Pipeline.id == automation.pipeline_id)
        )
        pipeline = pipeline_result.scalars().first()
        if pipeline is None or not pipeline.is_active:
            raise ValueError(
                "Automation 의 대상 Pipeline 이 없거나 비활성 상태입니다."
            )

        # 현재 최신 input versions 수집 (source split 별)
        config = PipelineConfig(**pipeline.config)
        latest_versions = await self._collect_latest_input_versions(config)

        # delta 판정 (if_delta 모드)
        last_seen = automation.last_seen_input_versions or {}
        has_delta = latest_versions != last_seen
        if request.mode == "if_delta" and not has_delta:
            # SKIPPED_NO_DELTA 레코드 남기고 종료 (026 §7 "skip 이력 유지")
            skip_run = PipelineRun(
                id=str(uuid.uuid4()),
                pipeline_id=pipeline.id,
                automation_id=automation.id,
                output_dataset_id=await self._sentinel_dataset_id(pipeline),
                transform_config=pipeline.config,
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
                automation_id=automation.id, pipeline_id=pipeline.id,
                latest_versions=latest_versions,
            )
            return PipelineSubmitResponse(
                execution_id=skip_run.id,
                celery_task_id=None,
                message="상류 입력 버전 변경 없음 — 실행 없이 SKIPPED_NO_DELTA 레코드만 남겼습니다.",
            )

        # force_latest 또는 delta 있는 if_delta — 실제 dispatch
        # pipeline_service.submit_run_from_pipeline 를 재사용하되 trigger_kind 만 변경
        from app.services.pipeline_service import PipelineService

        service = PipelineService(self.db)
        response = await service.submit_run_from_pipeline(
            pipeline.id, latest_versions,
        )

        # 방금 만들어진 run 을 찾아 trigger_kind / automation_id 후처리
        run_result = await self.db.execute(
            select(PipelineRun).where(PipelineRun.id == response.execution_id)
        )
        run = run_result.scalars().first()
        if run is not None:
            run.trigger_kind = "automation_manual_rerun"
            run.automation_trigger_source = "manual_rerun"
            run.automation_id = automation.id
            await self.db.flush()

        # last_seen_input_versions 갱신 — 자동 실행 성공 (or 적어도 디스패치) 시점
        automation.last_seen_input_versions = latest_versions
        await self.db.flush()
        return response

    # ─────────────────────────────────────────────────────────────────────────
    # 내부 헬퍼
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_pipeline_strict(self, pipeline_id: str) -> Pipeline:
        result = await self.db.execute(
            select(Pipeline).where(Pipeline.id == pipeline_id)
        )
        pipeline = result.scalars().first()
        if pipeline is None:
            raise ValueError(f"Pipeline not found: {pipeline_id}")
        return pipeline

    async def _collect_latest_input_versions(
        self, config: PipelineConfig,
    ) -> dict[str, str]:
        """
        config 가 참조하는 source split 들의 현재 최신 READY version 수집.
        """
        split_ids = set(config.get_all_source_split_ids())
        if not split_ids:
            return {}
        # split 별 최신 version 조회 (READY 상태만)
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
        필요. 현재 스키마는 이 컬럼이 NOT NULL 이므로 pipeline 의 output_split 에서 가장
        최근 DatasetVersion 을 재사용한다 (의미적으로는 "이 run 은 결과를 만들지 않음" —
        향후 output_dataset_id 를 nullable 로 승격하면 NULL 로 바꿀 수 있음, 027 §2-2
        주석 참조).
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
        # output 에 version 이 아직 없으면 임시 PENDING version 을 즉석 생성 — 운영상
        # 드문 케이스 (Pipeline 이 아직 한 번도 성공 실행된 적 없는 상태에서 skip 이력).
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
