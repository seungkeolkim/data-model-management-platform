"""
파이프라인 실행 서비스.

파이프라인 제출(submit) → Celery 태스크 디스패치, 실행 상태 조회 등을 처리한다.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.storage import get_storage_client
from app.models.all_models import (
    DatasetGroup,
    DatasetSplit,
    DatasetVersion,
    Pipeline,
    PipelineAutomation,
    PipelineRun,
)
from app.schemas.pipeline import PipelineSubmitResponse
from lib.pipeline.config import PartialPipelineConfig, PipelineConfig
from lib.pipeline.pipeline_validator import (
    PipelineValidationResult,
    validate_pipeline_config_static,
)

logger = structlog.get_logger(__name__)


class PipelineService:
    """파이프라인 실행 관련 비즈니스 로직."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = get_storage_client()

    # -------------------------------------------------------------------------
    # 파이프라인 검증
    # -------------------------------------------------------------------------

    async def validate_pipeline(self, config: PipelineConfig) -> PipelineValidationResult:
        """
        파이프라인 설정을 실행 전에 종합 검증한다.

        정적 검증(lib/ 레이어)과 DB 의존 검증을 모두 수행하여
        하나의 PipelineValidationResult로 통합 반환한다.
        Web UI에서 실행 전 검증 단계에서 호출한다.

        Args:
            config: 검증할 파이프라인 설정

        Returns:
            PipelineValidationResult — is_valid와 개별 issues 목록
        """
        # 1단계: 정적 검증 (DB 불필요)
        result = validate_pipeline_config_static(config)

        # 2단계: DB 의존 검증
        database_result = await self._validate_with_database(config)
        result.merge(database_result)

        if result.is_valid:
            logger.info("파이프라인 검증 통과", name=config.name)
        else:
            logger.warning(
                "파이프라인 검증 실패",
                name=config.name,
                error_count=result.error_count,
                warning_count=result.warning_count,
            )

        return result

    async def _validate_with_database(
        self, config: PipelineConfig
    ) -> PipelineValidationResult:
        """
        DB 조회가 필요한 검증을 수행한다.

        v1 (schema_version != 2) 경로: `source:<dataset_version_id>` 를 v1 방식으로 검증
        v2 (schema_version == 2)  경로: `source:<split_id>` 를 v2 방식으로 검증
            (split 존재 + group deleted 여부만 체크. version 은 실행 시점에 Resolver 에서)

        cls_merge / cls_set_head_labels / cls_filter_by_class / output_schema 호환성
        검증은 v1/v2 공통 — head_schema 는 group 레벨이므로 schema_version 과 무관.
        """
        result = PipelineValidationResult()

        # 모든 source ref 수집 (태스크별로 추적하여 field 정보 제공)
        for task_name, task_config in config.tasks.items():
            for source_ref in task_config.get_source_dataset_ids():
                await self._validate_source_ref(
                    source_ref, task_name, result, is_schema_v2=config.is_schema_v2,
                )

        # Passthrough 모드(tasks 비어있음)에서도 소스 검증
        if config.is_passthrough:
            if config.is_schema_v2 and config.passthrough_source_split_id:
                await self._validate_source_ref(
                    config.passthrough_source_split_id, "__passthrough__",
                    result, is_schema_v2=True,
                )
            elif not config.is_schema_v2 and config.passthrough_source_dataset_id:
                await self._validate_source_ref(
                    config.passthrough_source_dataset_id, "__passthrough__",
                    result, is_schema_v2=False,
                )

        # (4), (5), (6), (7) — 상류/출력 head_schema 를 preview 로 계산해야 하므로
        # 소스 검증이 먼저 통과한 경우에만 수행. 네 검사 모두
        # preview_head_schema_at_task 를 재사용하므로 source_meta_by_dataset_id 는
        # 호출 지점 각자가 필요 시 준비한다 (현재 구조 유지).
        if result.is_valid:
            await self._validate_cls_merge_compatibility(config, result)
            await self._validate_cls_set_head_labels_compatibility(config, result)
            await self._validate_cls_filter_by_class_compatibility(config, result)
            await self._validate_output_schema_compatibility(config, result)

        return result

    async def _validate_source_ref(
        self,
        source_ref: str,
        task_name: str,
        result: PipelineValidationResult,
        *,
        is_schema_v2: bool,
    ) -> None:
        """
        단일 `source:<X>` 참조에 대한 DB 검증 (v1/v2 분기).

        v2 (split_id 참조) — 저장 시점 검증:
          - DatasetSplit 존재
          - 상위 DatasetGroup 이 soft-delete 되지 않음
          (실제 version 선택 및 READY 상태 체크는 실행 시점 Version Resolver 에서)

        v1 (dataset_version_id 참조) — legacy 경로:
          - DatasetVersion 존재 + group soft-delete 아님 + status=READY + annotation_files 존재
        """
        if is_schema_v2:
            await self._validate_source_split_ref(source_ref, task_name, result)
        else:
            await self._validate_source_dataset_version_ref(
                source_ref, task_name, result,
            )

    async def _validate_source_split_ref(
        self,
        split_id: str,
        task_name: str,
        result: PipelineValidationResult,
    ) -> None:
        """v2 저장 시점 검증 — split_id 존재 + group 활성만 확인."""
        row = (await self.db.execute(
            select(DatasetSplit, DatasetGroup)
            .join(DatasetGroup, DatasetSplit.group_id == DatasetGroup.id)
            .where(DatasetSplit.id == split_id)
        )).first()
        if row is None:
            result.add_error(
                code="SOURCE_SPLIT_NOT_FOUND",
                message=(
                    f"태스크 '{task_name}'의 입력 split '{split_id}'를 찾을 수 없습니다. "
                    f"데이터셋이 삭제되었거나 다른 DB 환경일 수 있습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )
            return
        _split, group = row.tuple()
        if group.deleted_at is not None:
            result.add_error(
                code="SOURCE_DATASET_GROUP_DELETED",
                message=(
                    f"태스크 '{task_name}'의 입력 split 이 속한 그룹 '{group.name}'이(가) "
                    f"삭제되었습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )

    async def _validate_source_dataset_version_ref(
        self,
        dataset_id: str,
        task_name: str,
        result: PipelineValidationResult,
    ) -> None:
        """v1 legacy 경로 — 기존 검증 로직 그대로."""
        query_result = await self.db.execute(
            select(DatasetVersion, DatasetGroup)
            .join(DatasetSplit, DatasetVersion.split_id == DatasetSplit.id)
            .join(DatasetGroup, DatasetSplit.group_id == DatasetGroup.id)
            .where(DatasetVersion.id == dataset_id)
        )
        row = query_result.first()

        if row is None:
            result.add_error(
                code="SOURCE_DATASET_NOT_FOUND",
                message=(
                    f"태스크 '{task_name}'의 소스 데이터셋 '{dataset_id}'이(가) "
                    f"DB에 존재하지 않습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )
            return

        dataset, dataset_group = row.tuple()

        if dataset_group.deleted_at is not None:
            result.add_error(
                code="SOURCE_DATASET_GROUP_DELETED",
                message=(
                    f"태스크 '{task_name}'의 소스 데이터셋 '{dataset_id}'이(가) 속한 "
                    f"그룹 '{dataset_group.name}'이(가) 삭제되었습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )
            return

        if dataset.status != "READY":
            result.add_error(
                code="SOURCE_DATASET_NOT_READY",
                message=(
                    f"태스크 '{task_name}'의 소스 데이터셋 '{dataset_id}'의 "
                    f"상태가 '{dataset.status}'입니다. "
                    f"READY 상태의 데이터셋만 파이프라인 입력으로 사용할 수 있습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )

        if not dataset.annotation_files:
            result.add_warning(
                code="SOURCE_DATASET_NO_ANNOTATIONS",
                message=(
                    f"태스크 '{task_name}'의 소스 데이터셋 '{dataset_id}'에 "
                    f"annotation 파일이 등록되어 있지 않습니다."
                ),
                issue_field=f"tasks.{task_name}.inputs",
            )

    # v7.10 호환용 — 외부/테스트 호출부가 남아있으면 기존 v1 검증을 유지.
    _validate_source_dataset = _validate_source_dataset_version_ref

    async def _build_source_meta_map(
        self, config: PipelineConfig,
    ) -> dict[str, Any]:
        """
        config 의 모든 source ref 에 대해 head_schema 기반 stub meta 를 생성 (v7.10).

        반환 dict 의 key = source ref 값 (v1=dataset_version_id, v2=split_id).
        4개 validator (cls_merge / cls_set_head_labels / cls_filter_by_class /
        output_schema_compatibility) 가 동일한 key 로 meta 를 조회한다.

        head_schema 는 group 레벨 SSOT 이므로 version 무관 — v2 에서도 group 을 거슬러
        올라가면 동일 schema 를 얻는다.
        """
        from lib.pipeline.schema_preview import build_stub_source_meta

        meta_map: dict[str, Any] = {}
        if config.is_schema_v2:
            split_ids = config.get_all_source_split_ids()
            if not split_ids:
                return meta_map
            rows = (await self.db.execute(
                select(DatasetSplit)
                .options(selectinload(DatasetSplit.group))
                .where(DatasetSplit.id.in_(split_ids))
            )).scalars().all()
            for split_obj in rows:
                head_schema = split_obj.group.head_schema if split_obj.group else None
                meta_map[split_obj.id] = build_stub_source_meta(
                    dataset_id=split_obj.id,  # key 는 split_id, stub 의 dataset_id 도 같은 값
                    head_schema_json=head_schema,
                )
        else:
            for dataset_id in config.get_all_source_dataset_ids():
                dataset_row = await self.db.execute(
                    select(DatasetVersion)
                    .options(
                        selectinload(DatasetVersion.split_slot)
                        .selectinload(DatasetSplit.group)
                    )
                    .where(
                        DatasetVersion.id == dataset_id,
                        DatasetVersion.deleted_at.is_(None),
                    )
                )
                dataset_obj = dataset_row.scalar_one_or_none()
                if dataset_obj is None:
                    continue
                head_schema = (
                    dataset_obj.group.head_schema if dataset_obj.group else None
                )
                meta_map[dataset_id] = build_stub_source_meta(
                    dataset_id=dataset_id,
                    head_schema_json=head_schema,
                )
        return meta_map

    # -------------------------------------------------------------------------
    # cls_merge_datasets 호환성 검증 (§2-11-2)
    # -------------------------------------------------------------------------

    async def _validate_cls_merge_compatibility(
        self,
        config: PipelineConfig,
        result: PipelineValidationResult,
    ) -> None:
        """
        config 내 cls_merge_datasets 태스크마다 입력들의 head_schema 를 preview 로 계산해
        `check_merge_schema_compatibility` 로 검증한다.

        FE 는 노드 단위로 정적 검증을 선행하지만, API 우회(FE 미사용) 요청에 대비해
        BE 도 동일 규칙을 수행한다. 두 경로 모두 `lib/pipeline/cls_merge_compat.py` 의
        동일 함수를 호출해 규칙 드리프트를 막는다.

        head_schema 는 DatasetGroup 에 저장되어 있으므로 preview_head_schema_at_task 를
        재사용해 각 입력 시점의 최종 head_schema 를 얻는다. 입력 중 하나라도 preview 가
        실패하면 해당 head_schema 만 None 으로 처리해 호환성 함수가 TASK_KIND_MISMATCH 로
        보고하게 한다 (일부 실패 시에도 나머지 이슈가 누락되지 않도록).
        """
        # 지연 import — lib 초기화 순서 문제 회피.
        from lib.pipeline.cls_merge_compat import (
            check_merge_schema_compatibility,
        )
        from lib.pipeline.schema_preview import (
            SchemaPreviewError,
            build_stub_source_meta,
            preview_head_schema_at_task,
        )

        cls_merge_tasks = [
            (task_name, task_config)
            for task_name, task_config in config.tasks.items()
            if task_config.operator == "cls_merge_datasets"
        ]
        if not cls_merge_tasks:
            return

        # source head_schema stub meta 미리 로드 — v7.10 공통 헬퍼 사용 (v1/v2 분기 포함)
        source_meta_by_dataset_id = await self._build_source_meta_map(config)

        for task_name, task_config in cls_merge_tasks:
            input_head_schemas: list[Any] = []
            for ref in task_config.inputs:
                if ref.startswith("source:"):
                    source_dataset_id = ref.split(":", 1)[1]
                    source_meta = source_meta_by_dataset_id.get(source_dataset_id)
                    input_head_schemas.append(
                        getattr(source_meta, "head_schema", None)
                    )
                    continue

                # task ref: 해당 task 출력의 head_schema 를 preview 로 계산.
                try:
                    upstream_meta = preview_head_schema_at_task(
                        config=config,  # type: ignore[arg-type]  # PipelineConfig 는 duck-typed 로 PartialPipelineConfig 와 호환
                        target_task_name=ref,
                        source_meta_by_dataset_id=source_meta_by_dataset_id,
                    )
                    input_head_schemas.append(upstream_meta.head_schema)
                except SchemaPreviewError as preview_error:
                    # 상류 계산 실패는 별도 경고로 남기고 head_schema=None 으로 취급.
                    result.add_warning(
                        code="MERGE_UPSTREAM_PREVIEW_FAILED",
                        message=(
                            f"태스크 '{task_name}'의 입력 '{ref}' 의 head_schema 를 "
                            f"계산하지 못해 호환성 검사를 건너뜁니다: "
                            f"[{preview_error.code}] {preview_error.message}"
                        ),
                        issue_field=f"tasks.{task_name}.inputs",
                    )
                    input_head_schemas.append(None)

            issues = check_merge_schema_compatibility(
                input_head_schemas,
                task_config.params,
            )
            for issue in issues:
                result.add_error(
                    code=f"MERGE_{issue.code}",
                    message=issue.message,
                    issue_field=f"tasks.{task_name}.{issue.field_suffix}",
                )

    # -------------------------------------------------------------------------
    # cls_set_head_labels_for_all_images 정적 검증 (§2-4 SSOT / §2-12 null 규약)
    # -------------------------------------------------------------------------

    async def _validate_cls_set_head_labels_compatibility(
        self,
        config: PipelineConfig,
        result: PipelineValidationResult,
    ) -> None:
        """
        config 내 cls_set_head_labels_for_all_images 태스크마다 상류 head_schema 를
        preview 로 계산해 `validate_set_head_labels_params` 로 검증한다.

        이 검증이 필요한 이유:
            runtime 의 `transform_annotation` 이 이미 동일 규칙을 검사하지만, 정적
            `/pipelines/validate` 단계에서는 DAG 를 실제 실행하지 않으므로 단일 노드
            의 runtime 검증이 호출되지 않는다 (pipeline id a6e6b2a2-... 재현 버그).
            상류 head_schema 를 preview 로 시뮬레이션한 뒤 params 와 대조해, 사용자
            가 `/execute` 를 누르기 전에 UI 에 이슈를 노출한다.

        단일 입력 노드이므로 입력 ref 는 정확히 1 개. 0 개/2 개 이상은 NodeKind 정적
        검증이 선행 차단한다.

        상류 preview 가 실패하면 경고로만 남기고 본검증은 skip — 동일한 원인을
        이중 에러로 띄우지 않는다.
        """
        from lib.manipulators.cls_set_head_labels_for_all_images import (
            validate_set_head_labels_params,
        )
        from lib.pipeline.schema_preview import (
            SchemaPreviewError,
            build_stub_source_meta,
            preview_head_schema_at_task,
        )

        target_tasks = [
            (task_name, task_config)
            for task_name, task_config in config.tasks.items()
            if task_config.operator == "cls_set_head_labels_for_all_images"
        ]
        if not target_tasks:
            return

        # v7.10 공통 헬퍼로 source head_schema stub meta 로드 (cls_set_head_labels compat)
        source_meta_by_dataset_id = await self._build_source_meta_map(config)

        for task_name, task_config in target_tasks:
            if len(task_config.inputs) != 1:
                # 단일 입력이 아닌 경우 NodeKind validator 가 잡을 문제 — skip.
                continue
            upstream_ref = task_config.inputs[0]

            if upstream_ref.startswith("source:"):
                source_dataset_id = upstream_ref.split(":", 1)[1]
                upstream_meta = source_meta_by_dataset_id.get(source_dataset_id)
                if upstream_meta is None:
                    # 앞선 _validate_source_dataset 에서 이미 에러로 잡힘.
                    continue
                upstream_head_schema = getattr(upstream_meta, "head_schema", None)
            else:
                try:
                    upstream_meta = preview_head_schema_at_task(
                        config=config,  # type: ignore[arg-type]
                        target_task_name=upstream_ref,
                        source_meta_by_dataset_id=source_meta_by_dataset_id,
                    )
                except SchemaPreviewError as preview_error:
                    result.add_warning(
                        code="SET_HEAD_LABELS_UPSTREAM_PREVIEW_FAILED",
                        message=(
                            f"태스크 '{task_name}' 의 입력 '{upstream_ref}' 의 "
                            f"head_schema 를 계산하지 못해 params 검증을 건너뜁니다: "
                            f"[{preview_error.code}] {preview_error.message}"
                        ),
                        issue_field=f"tasks.{task_name}.inputs",
                    )
                    continue
                upstream_head_schema = upstream_meta.head_schema

            issues = validate_set_head_labels_params(
                upstream_head_schema, task_config.params,
            )
            for issue_code, issue_message in issues:
                result.add_error(
                    code=f"SET_HEAD_LABELS_{issue_code}",
                    message=issue_message,
                    issue_field=f"tasks.{task_name}.params",
                )

    # -------------------------------------------------------------------------
    # cls_filter_by_class 정적 검증 (§2-4 SSOT / §2-12 null 규약)
    # -------------------------------------------------------------------------

    async def _validate_cls_filter_by_class_compatibility(
        self,
        config: PipelineConfig,
        result: PipelineValidationResult,
    ) -> None:
        """
        config 내 cls_filter_by_class 태스크마다 상류 head_schema 를 preview 로 계산해
        `validate_filter_by_class_params` 로 검증한다.

        cls_set_head_labels_for_all_images 와 동일 패턴 — runtime
        `transform_annotation` 이 이미 동일 규칙을 적용하지만, 정적
        `/pipelines/validate` 단계에서는 DAG 를 실행하지 않으므로 여기서도 검사해
        사용자가 `/execute` 전에 UI 에서 이슈를 확인할 수 있게 한다.

        상류 preview 가 실패하면 경고로 degrade 하고 본 검증은 skip.
        """
        from lib.manipulators.cls_filter_by_class import (
            validate_filter_by_class_params,
        )
        from lib.pipeline.schema_preview import (
            SchemaPreviewError,
            build_stub_source_meta,
            preview_head_schema_at_task,
        )

        target_tasks = [
            (task_name, task_config)
            for task_name, task_config in config.tasks.items()
            if task_config.operator == "cls_filter_by_class"
        ]
        if not target_tasks:
            return

        # v7.10 공통 헬퍼 — cls_filter_by_class compat
        source_meta_by_dataset_id = await self._build_source_meta_map(config)

        for task_name, task_config in target_tasks:
            if len(task_config.inputs) != 1:
                # 단일 입력이 아닌 경우 NodeKind validator 가 잡을 문제 — skip.
                continue
            upstream_ref = task_config.inputs[0]

            if upstream_ref.startswith("source:"):
                source_dataset_id = upstream_ref.split(":", 1)[1]
                upstream_meta = source_meta_by_dataset_id.get(source_dataset_id)
                if upstream_meta is None:
                    # 앞선 _validate_source_dataset 에서 이미 에러로 잡힘.
                    continue
                upstream_head_schema = getattr(upstream_meta, "head_schema", None)
            else:
                try:
                    upstream_meta = preview_head_schema_at_task(
                        config=config,  # type: ignore[arg-type]
                        target_task_name=upstream_ref,
                        source_meta_by_dataset_id=source_meta_by_dataset_id,
                    )
                except SchemaPreviewError as preview_error:
                    result.add_warning(
                        code="FILTER_BY_CLASS_UPSTREAM_PREVIEW_FAILED",
                        message=(
                            f"태스크 '{task_name}' 의 입력 '{upstream_ref}' 의 "
                            f"head_schema 를 계산하지 못해 params 검증을 건너뜁니다: "
                            f"[{preview_error.code}] {preview_error.message}"
                        ),
                        issue_field=f"tasks.{task_name}.inputs",
                    )
                    continue
                upstream_head_schema = upstream_meta.head_schema

            issues = validate_filter_by_class_params(
                upstream_head_schema, task_config.params,
            )
            for issue_code, issue_message in issues:
                result.add_error(
                    code=f"FILTER_BY_CLASS_{issue_code}",
                    message=issue_message,
                    issue_field=f"tasks.{task_name}.params",
                )

    # -------------------------------------------------------------------------
    # 출력 head_schema 호환성 검증 — 설계서 §2-8 단일 원칙 강제
    # -------------------------------------------------------------------------

    async def _validate_output_schema_compatibility(
        self,
        config: PipelineConfig,
        result: PipelineValidationResult,
    ) -> None:
        """
        파이프라인 출력의 head_schema 가 기존 동명 그룹의 head_schema 와 다르면
        OUTPUT_SCHEMA_MISMATCH ERROR 를 추가한다.

        설계서 §2-8 단일 원칙:
            "같은 Group 의 모든 Dataset 은 동일 head_schema 를 가진다."
            schema 가 달라지면 사용자는 다른 그룹명으로 저장해야 한다.

        분기:
            - 신규 그룹 (동명 그룹 없음) → skip. 파이프라인 완료 시 group.head_schema
              가 setdefault 로 이번 출력 schema 로 초기화된다.
            - 기존 그룹이 detection (task_types 에 CLASSIFICATION 없음) → skip.
              이 시점에서 classification 출력과의 불일치는 상류 compat 검증에서
              이미 포착되므로 중복 체크하지 않는다.
            - 기존 그룹이 classification 인데 head_schema NULL → warning. 이번
              실행이 초기화하므로 통과시키되 사용자에게 주의 환기 (backfill 권고).
            - classification 그룹 + head_schema 있음 → 출력 schema 를 preview 로
              계산해 _diff_head_schema 로 비교. 차이가 있으면 ERROR.
        """
        from lib.pipeline.schema_preview import (
            SchemaPreviewError,
            build_stub_source_meta,
            preview_head_schema_at_task,
        )
        from app.services.dataset_service import _diff_head_schema

        # 1) 출력 대상 기존 그룹 조회 (_find_or_create_dataset_group 과 동일 키 사용)
        output_name = config.name
        output_dataset_type = config.output.dataset_type.upper()
        existing_group_row = await self.db.execute(
            select(DatasetGroup).where(
                DatasetGroup.name == output_name,
                DatasetGroup.dataset_type == output_dataset_type,
                DatasetGroup.deleted_at.is_(None),
            )
        )
        existing_group = existing_group_row.scalar_one_or_none()
        if existing_group is None:
            return  # 신규 그룹 — schema 는 파이프라인 완료 시 setdefault 로 세팅됨
        if "CLASSIFICATION" not in (existing_group.task_types or []):
            return  # detection 그룹 — 이 함수의 대상 아님
        if existing_group.head_schema is None:
            # classification 그룹인데 head_schema 가 NULL — 과거 버그로 생긴 상태.
            # 이번 실행이 setdefault 로 초기화해줄 것이므로 warning 만 남긴다.
            result.add_warning(
                code="OUTPUT_GROUP_HEAD_SCHEMA_MISSING",
                message=(
                    f"기존 출력 그룹 '{output_name}' 의 head_schema 가 비어 있습니다. "
                    "이번 파이프라인 완료 시 현재 출력 schema 로 초기화됩니다. "
                    "데이터 무결성 검토를 권장합니다."
                ),
                issue_field="name",
            )
            return

        # 2) 출력 head_schema 계산 — passthrough / tasks 분기
        # v7.10 공통 헬퍼 사용 (v1/v2 둘 다 처리). classification 소스가 없으면
        # passthrough/preview 모두 head_schema=None 을 리턴해 아래 분기에서 자연 처리.
        source_meta_by_dataset_id = await self._build_source_meta_map(config)

        # passthrough 참조 해석 — v2 는 split_id, v1 은 dataset_version_id
        passthrough_source_ref: str | None = None
        if config.is_passthrough:
            if config.is_schema_v2 and config.passthrough_source_split_id:
                passthrough_source_ref = config.passthrough_source_split_id
            elif not config.is_schema_v2 and config.passthrough_source_dataset_id:
                passthrough_source_ref = config.passthrough_source_dataset_id

        output_head_schema_list = None
        if passthrough_source_ref:
            passthrough_meta = source_meta_by_dataset_id.get(passthrough_source_ref)
            if passthrough_meta is None:
                return  # 소스 로드 실패 — 다른 검증 항목에서 에러 보고됨
            output_head_schema_list = getattr(passthrough_meta, "head_schema", None)
        else:
            try:
                terminal_task_name = config.get_terminal_task_name()
            except ValueError:
                return  # sink 구성 에러는 정적 검증에서 이미 에러로 수집됨
            try:
                terminal_meta = preview_head_schema_at_task(
                    config=config,
                    target_task_name=terminal_task_name,
                    source_meta_by_dataset_id=source_meta_by_dataset_id,  # type: ignore[arg-type]
                )
            except SchemaPreviewError:
                # preview 실패 — merge/set_head_labels/filter compat 에서 이미 보고됨.
                return
            output_head_schema_list = terminal_meta.head_schema

        if output_head_schema_list is None:
            # 출력 schema 가 없는데 기존 그룹이 classification — 타입 자체 불일치.
            result.add_error(
                code="OUTPUT_SCHEMA_MISMATCH",
                message=(
                    f"파이프라인 출력에 head_schema 가 없는데 기존 그룹 "
                    f"'{output_name}' 은 classification 입니다. 다른 출력 "
                    "그룹명을 지정하세요."
                ),
                issue_field="name",
            )
            return

        # 3) 기존 group.head_schema 와 비교 — _diff_head_schema 를 재사용.
        new_head_schema_dict = {
            "heads": [
                {
                    "name": head.name,
                    "multi_label": head.multi_label,
                    "classes": list(head.classes),
                }
                for head in output_head_schema_list
            ],
        }
        try:
            _diff_head_schema(existing_group.head_schema, new_head_schema_dict)
        except ValueError as diff_err:
            result.add_error(
                code="OUTPUT_SCHEMA_MISMATCH",
                message=(
                    f"파이프라인 출력의 head_schema 가 기존 그룹 "
                    f"'{output_name}' 의 head_schema 와 다릅니다. 설계서 "
                    "§2-8 에 따라 schema 가 다른 데이터는 새 그룹으로 "
                    f"저장해야 합니다. 다른 출력 그룹명을 지정하세요. "
                    f"차이: {str(diff_err)}"
                ),
                issue_field="name",
            )

    # -------------------------------------------------------------------------
    # 파이프라인 제출
    # -------------------------------------------------------------------------

    async def submit_pipeline(self, config: PipelineConfig) -> PipelineSubmitResponse:
        """
        파이프라인 실행을 제출한다.

        1. DatasetGroup 조회 또는 생성 (config.name + config.output.dataset_type)
        2. Dataset 생성 (status=PENDING)
        3. PipelineRun 생성 (status=PENDING)
        4. Celery 태스크 디스패치
        5. PipelineSubmitResponse 반환

        Args:
            config: DAG 기반 파이프라인 설정 (Pydantic 모델)

        Returns:
            PipelineSubmitResponse (execution_id, celery_task_id, message)
        """
        dataset_type = config.output.dataset_type.upper()
        annotation_format = config.output.annotation_format.upper()
        split = config.output.split.upper()

        # ── 소스 데이터셋 그룹들의 task_types 교집합 계산 ──
        source_task_types = await self._intersect_source_task_types(config)

        # ── DatasetGroup 조회 또는 생성 ──
        group = await self._find_or_create_dataset_group(
            name=config.name,
            dataset_type=dataset_type,
            annotation_format=annotation_format,
            task_types=source_task_types,
        )

        # ── Split 슬롯 선조회/생성 → 버전 자동 생성 (v7.9 3계층 분리) ──
        split_slot = await self._get_or_create_split(group.id, split)
        version = await self._next_version(split_slot.id)
        logger.info(
            "파이프라인 출력 버전 결정",
            group_name=group.name, split=split, version=version,
        )

        # ── storage_uri 사전 생성 ──
        storage_uri = self.storage.build_dataset_uri(
            dataset_type=dataset_type,
            name=config.name,
            split=split,
            version=version,
        )

        # ── DatasetVersion 생성 (status=PENDING) ──
        dataset = DatasetVersion(
            id=str(uuid.uuid4()),
            split_id=split_slot.id,
            version=version,
            annotation_format=annotation_format,
            storage_uri=storage_uri,
            status="PENDING",
        )
        self.db.add(dataset)
        await self.db.flush()
        logger.info("출력 Dataset 생성", dataset_id=dataset.id, storage_uri=storage_uri)

        # ── Pipeline (정적 템플릿) 조회 또는 생성 (v7.10, 027 §2-1 + §12-1) ──
        # TODO §9-3: "저장/실행 분리" UX 구현 시 이 경로는 "실행" 엔드포인트 전용이 되고,
        # Pipeline 생성은 별도 "저장" 엔드포인트로 분리된다. 현재는 호환을 위해 submit 에서
        # Pipeline 을 get-or-create 한다. name 자동 생성 규칙은 §12-2 (`{group}_{split}`)
        # 이지만 현 단계에서는 config.name (= group 이름) 에 `_{split}` 를 붙여 UNIQUE
        # (name, version) 을 만족시키는 최소 규칙으로.
        pipeline_task_type = (source_task_types[0] if source_task_types else "DETECTION")
        pipeline = await self._get_or_create_pipeline_for_submit(
            config=config,
            output_split_id=split_slot.id,
            task_type=pipeline_task_type,
            split=split,
        )

        # ── resolved_input_versions 추출 (현재 시점의 input 버전 스냅샷, 기본 = 최신) ──
        resolved_input_versions = await self._extract_resolved_input_versions(config)

        # ── v2 config 을 실행용 resolved config 으로 치환 (§9-5) ──
        # source:<split_id> → source:<dataset_version_id>. Celery executor 는 기존대로
        # dataset_version_id 를 읽어서 동작. transform_config 스냅샷에도 동일 resolved 저장.
        config_dict_raw = config.model_dump()
        if config.is_schema_v2:
            split_to_dataset = await self._resolve_versions_to_dataset_ids(
                resolved_input_versions
            )
            resolved_config_dict = self._substitute_v2_to_resolved_config(
                config_dict_raw, split_to_dataset,
            )
        else:
            resolved_config_dict = config_dict_raw

        # ── PipelineRun 생성 (v7.10 — 기존 PipelineExecution rename + 확장) ──
        execution = PipelineRun(
            id=str(uuid.uuid4()),
            pipeline_id=pipeline.id,
            output_dataset_id=dataset.id,
            transform_config=resolved_config_dict,
            resolved_input_versions=resolved_input_versions,
            trigger_kind="manual_from_editor",
            status="PENDING",
        )
        self.db.add(execution)
        await self.db.flush()

        # ── Celery 태스크 디스패치 — executor 는 v1 형식으로 해석하므로 resolved 를 전달 ──
        from app.tasks.pipeline_tasks import run_pipeline

        celery_result = run_pipeline.delay(
            execution.id,
            resolved_config_dict,
        )
        celery_task_id = celery_result.id

        execution.celery_task_id = celery_task_id
        await self.db.flush()

        logger.info(
            "파이프라인 Celery 태스크 디스패치 완료",
            execution_id=execution.id,
            celery_task_id=celery_task_id,
            schema_version=config.schema_version,
        )

        return PipelineSubmitResponse(
            execution_id=execution.id,
            celery_task_id=celery_task_id,
            message="파이프라인이 제출되었습니다.",
        )

    # -------------------------------------------------------------------------
    # 실행 상태 조회
    # -------------------------------------------------------------------------

    async def get_execution_status(self, execution_id: str) -> PipelineRun | None:
        """PipelineRun 단건 조회 (output_dataset eager load)."""
        result = await self.db.execute(
            select(PipelineRun)
            .options(
                selectinload(PipelineRun.output_dataset)
                .selectinload(DatasetVersion.split_slot)
            )
            .where(PipelineRun.id == execution_id)
        )
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # 실행 이력 목록
    # -------------------------------------------------------------------------

    async def list_executions(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PipelineRun], int]:
        """PipelineRun 목록 조회 (페이지네이션, 최신순, output_dataset eager load)."""
        base_query = select(PipelineRun)

        count_query = select(func.count()).select_from(base_query.subquery())
        total = await self.db.scalar(count_query) or 0

        list_query = (
            base_query
            .options(
                selectinload(PipelineRun.output_dataset)
                .selectinload(DatasetVersion.split_slot)
            )
            .order_by(PipelineRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(list_query)
        items = list(result.scalars().all())

        return items, total

    # -------------------------------------------------------------------------
    # Schema 프리뷰
    # -------------------------------------------------------------------------

    async def preview_head_schema(
        self,
        config: PartialPipelineConfig,
        target_ref: str,
    ) -> dict:
        """
        지정 노드 시점의 head_schema 를 계산해 dict 로 반환.

        target_ref 규약:
            - "task_{nodeId}"  : operator/merge 노드 출력
            - "source:{dataset_id}" : dataLoad 노드 출력 (소스 head_schema 그대로)

        반환 dict 구조:
            {
              "task_kind": "classification" | "detection" | "unknown",
              "head_schema": {"heads": [...]} | None,
              "error_code": str | None,
              "error_message": str | None,
            }
        """
        # 지연 import — FastAPI 앱 기동 시 lib 모듈 초기화 순서 문제 회피.
        from lib.pipeline.schema_preview import (
            SchemaPreviewError,
            build_stub_source_meta,
            head_schema_to_list,
            preview_head_schema_at_task,
        )

        def _is_classification_group(task_types: list[str] | None) -> bool:
            """
            DatasetGroup 이 classification 그룹인지 판정.

            판정 SSOT 는 `DatasetGroup.task_types` 컬럼이다. head_schema 컬럼의
            존재 여부로 판정하지 않는 이유: classification 그룹인데 head_schema
            가 NULL 인 상태 (파이프라인이 출력한 SOURCE/FUSION 그룹에서 발생) 는
            내부 데이터 무결성 버그이고, 이를 detection 으로 간주해 UI 에서 숨기면
            원인 추적이 어렵다. task_types 기준으로 판정하고 head_schema 가
            없는 경우는 별도 error_message 로 사용자에게 알린다.
            """
            return "CLASSIFICATION" in (task_types or [])

        # 1) 파이프라인에서 참조하는 모든 source 의 head_schema + task_types 를 DB 에서 로드.
        #    v1 (dataset_version_id) / v2 (split_id) 분기. task_ 분기에서 그룹 판정에 사용.
        source_meta_by_dataset_id: dict[str, object] = {}
        source_task_types_by_dataset_id: dict[str, list[str]] = {}

        is_v2 = getattr(config, "is_schema_v2", False) or (
            getattr(config, "schema_version", None) == 2
        )
        if is_v2:
            split_ids = config.get_all_source_split_ids()
            for split_id in split_ids:
                split_row = await self.db.execute(
                    select(DatasetSplit)
                    .options(selectinload(DatasetSplit.group))
                    .where(DatasetSplit.id == split_id)
                )
                split_obj = split_row.scalar_one_or_none()
                if split_obj is None:
                    return {
                        "task_kind": "unknown",
                        "head_schema": None,
                        "error_code": "SOURCE_NOT_FOUND",
                        "error_message": (
                            f"source split_id='{split_id}' 를 DB 에서 찾을 수 없습니다."
                        ),
                    }
                group_head_schema = (
                    split_obj.group.head_schema if split_obj.group else None
                )
                group_task_types = (
                    split_obj.group.task_types if split_obj.group else None
                )
                source_meta_by_dataset_id[split_id] = build_stub_source_meta(
                    dataset_id=split_id,
                    head_schema_json=group_head_schema,
                )
                source_task_types_by_dataset_id[split_id] = group_task_types or []
        else:
            source_dataset_ids = config.get_all_source_dataset_ids()
            for dataset_id in source_dataset_ids:
                dataset_row = await self.db.execute(
                    select(DatasetVersion)
                    .options(selectinload(DatasetVersion.split_slot).selectinload(DatasetSplit.group))
                    .where(DatasetVersion.id == dataset_id, DatasetVersion.deleted_at.is_(None))
                )
                dataset_obj = dataset_row.scalar_one_or_none()
                if dataset_obj is None:
                    return {
                        "task_kind": "unknown",
                        "head_schema": None,
                        "error_code": "SOURCE_NOT_FOUND",
                        "error_message": (
                            f"source dataset_id='{dataset_id}' 를 DB 에서 찾을 수 없습니다."
                        ),
                    }
                group_head_schema = (
                    dataset_obj.group.head_schema if dataset_obj.group else None
                )
                group_task_types = (
                    dataset_obj.group.task_types if dataset_obj.group else None
                )
                source_meta_by_dataset_id[dataset_id] = build_stub_source_meta(
                    dataset_id=dataset_id,
                    head_schema_json=group_head_schema,
                )
                source_task_types_by_dataset_id[dataset_id] = group_task_types or []

        # 2) target_ref 분기.
        #
        # source:<id> 타겟은 config 참조 여부와 무관하게 해당 dataset 의
        # head_schema 를 DB 에서 직접 읽어 반환한다. dataLoad 노드 단독으로
        # 선택된 경우 (config.tasks 와 passthrough 가 비어 있어 해당 source 가
        # source_meta_by_dataset_id 에 포함되지 않을 수 있다) 에도 프리뷰가
        # 정상 동작하도록 하기 위함.
        if target_ref.startswith("source:"):
            source_ref_value = target_ref.split(":", 1)[1]
            source_meta = source_meta_by_dataset_id.get(source_ref_value)
            group_task_types = source_task_types_by_dataset_id.get(source_ref_value)
            if source_meta is None:
                # config 에 참조되지 않은 source — dataLoad 단독 선택 등.
                # v1 (dataset_version_id) / v2 (split_id) 분기하여 DB 에서 직접 로드.
                group_obj = None
                if is_v2:
                    split_row = await self.db.execute(
                        select(DatasetSplit)
                        .options(selectinload(DatasetSplit.group))
                        .where(DatasetSplit.id == source_ref_value)
                    )
                    split_obj = split_row.scalar_one_or_none()
                    if split_obj is None:
                        return {
                            "task_kind": "unknown",
                            "head_schema": None,
                            "error_code": "SOURCE_NOT_FOUND",
                            "error_message": (
                                f"source split_id='{source_ref_value}' 를 DB 에서 찾을 수 없습니다."
                            ),
                        }
                    group_obj = split_obj.group
                else:
                    dataset_row = await self.db.execute(
                        select(DatasetVersion)
                        .options(selectinload(DatasetVersion.split_slot).selectinload(DatasetSplit.group))
                        .where(
                            DatasetVersion.id == source_ref_value,
                            DatasetVersion.deleted_at.is_(None),
                        )
                    )
                    dataset_obj = dataset_row.scalar_one_or_none()
                    if dataset_obj is None:
                        return {
                            "task_kind": "unknown",
                            "head_schema": None,
                            "error_code": "SOURCE_NOT_FOUND",
                            "error_message": (
                                f"source dataset_id='{source_ref_value}' 를 DB 에서 찾을 수 없습니다."
                            ),
                        }
                    group_obj = dataset_obj.group
                group_head_schema = group_obj.head_schema if group_obj else None
                group_task_types = group_obj.task_types if group_obj else None
                source_meta = build_stub_source_meta(
                    dataset_id=source_ref_value,
                    head_schema_json=group_head_schema,
                )
            head_schema = getattr(source_meta, "head_schema", None)
            # task_kind 는 group.task_types 기준으로 판정. classification 그룹인데
            # head_schema 가 비어 있으면 무결성 에러로 경고한다 (숨기지 않음).
            if _is_classification_group(group_task_types):
                if head_schema is None:
                    return {
                        "task_kind": "classification",
                        "head_schema": None,
                        "error_code": "HEAD_SCHEMA_MISSING",
                        "error_message": (
                            "classification 그룹이지만 DatasetGroup.head_schema 가 "
                            "비어 있습니다. 파이프라인 결과로 생성된 그룹일 경우 "
                            "데이터 무결성 문제이므로 재생성하거나 백필이 필요합니다."
                        ),
                    }
                return {
                    "task_kind": "classification",
                    "head_schema": head_schema_to_list(head_schema),
                    "error_code": None,
                    "error_message": None,
                }
            return {
                "task_kind": "detection",
                "head_schema": None,
                "error_code": None,
                "error_message": None,
            }

        # 3) task_{...} 타겟. classification 그룹 source 가 하나도 없으면
        #    프리뷰 대상이 아님. (source:<id> 분기는 위에서 이미 처리.)
        any_classification_group = any(
            _is_classification_group(task_types)
            for task_types in source_task_types_by_dataset_id.values()
        )
        if not any_classification_group:
            return {
                "task_kind": "detection",
                "head_schema": None,
                "error_code": None,
                "error_message": None,
            }

        try:
            result_meta = preview_head_schema_at_task(
                config=config,
                target_task_name=target_ref,
                source_meta_by_dataset_id=source_meta_by_dataset_id,  # type: ignore[arg-type]
            )
        except SchemaPreviewError as preview_error:
            return {
                "task_kind": "classification",
                "head_schema": None,
                "error_code": preview_error.code,
                "error_message": preview_error.message,
            }

        # task_ 분기는 상류가 classification 그룹이라고 판정된 이후이므로
        # 결과도 classification 으로 확정. head_schema 가 None 이면 상류 그룹의
        # head_schema 컬럼이 비어 있었다는 뜻 → 사용자에게 경고.
        result_head_schema = result_meta.head_schema
        if result_head_schema is None:
            return {
                "task_kind": "classification",
                "head_schema": None,
                "error_code": "HEAD_SCHEMA_MISSING",
                "error_message": (
                    "상류 classification 그룹의 DatasetGroup.head_schema 가 "
                    "비어 있어 이 노드 시점의 schema 를 계산하지 못했습니다. "
                    "소스 그룹의 head_schema 복구가 필요합니다."
                ),
            }
        return {
            "task_kind": "classification",
            "head_schema": head_schema_to_list(result_head_schema),
            "error_code": None,
            "error_message": None,
        }

    # -------------------------------------------------------------------------
    # 내부 헬퍼
    # -------------------------------------------------------------------------

    async def _find_or_create_dataset_group(
        self,
        name: str,
        dataset_type: str,
        annotation_format: str,
        task_types: list[str] | None = None,
    ) -> DatasetGroup:
        """
        이름 + dataset_type으로 기존 그룹을 찾고, 없으면 새로 생성한다.
        소프트 삭제된 그룹은 무시한다.
        기존 그룹이 있고 task_types가 비어 있으면, 전달된 task_types로 업데이트한다.
        """
        result = await self.db.execute(
            select(DatasetGroup).where(
                DatasetGroup.name == name,
                DatasetGroup.dataset_type == dataset_type,
                DatasetGroup.deleted_at.is_(None),
            )
        )
        existing_group = result.scalar_one_or_none()

        if existing_group is not None:
            # 기존 그룹에 task_types가 없으면 소스 교집합으로 채운다
            if not existing_group.task_types and task_types:
                existing_group.task_types = task_types
                logger.info(
                    "기존 DatasetGroup task_types 자동 설정",
                    group_id=existing_group.id,
                    task_types=task_types,
                )
            logger.info(
                "기존 DatasetGroup 사용",
                group_id=existing_group.id, group_name=existing_group.name,
            )
            return existing_group

        new_group = DatasetGroup(
            id=str(uuid.uuid4()),
            name=name,
            dataset_type=dataset_type,
            annotation_format=annotation_format,
            task_types=task_types,
        )
        self.db.add(new_group)
        await self.db.flush()
        logger.info(
            "신규 DatasetGroup 생성",
            group_id=new_group.id, group_name=new_group.name,
            task_types=task_types,
        )
        return new_group

    async def _intersect_source_task_types(
        self, config: PipelineConfig,
    ) -> list[str] | None:
        """
        파이프라인 config 의 소스들이 속한 그룹들의 task_types 교집합 반환.
        소스가 없거나 교집합이 비어 있으면 None.

        v7.10 schema_version 분기:
          v2 — config 의 source ref = split_id 직접. split → group 1단 JOIN
          v1 — source ref = dataset_version_id. version → split → group 2단 JOIN
        """
        if config.is_schema_v2:
            split_ids: set[str] = set(config.get_all_source_split_ids())
            if not split_ids:
                return None
            result = await self.db.execute(
                select(DatasetGroup.task_types)
                .join(DatasetSplit, DatasetSplit.group_id == DatasetGroup.id)
                .where(DatasetSplit.id.in_(split_ids))
                .distinct()
            )
        else:
            source_dataset_ids: set[str] = set(config.get_all_source_dataset_ids())
            if not source_dataset_ids:
                return None
            result = await self.db.execute(
                select(DatasetGroup.task_types)
                .join(DatasetSplit, DatasetSplit.group_id == DatasetGroup.id)
                .join(DatasetVersion, DatasetVersion.split_id == DatasetSplit.id)
                .where(DatasetVersion.id.in_(source_dataset_ids))
                .distinct()
            )
        all_task_types_rows = result.scalars().all()

        # 교집합 계산
        intersection: set[str] | None = None
        for task_types_row in all_task_types_rows:
            if not task_types_row:
                continue
            current_set = set(task_types_row)
            if intersection is None:
                intersection = current_set
            else:
                intersection &= current_set

        if not intersection:
            return None

        return sorted(intersection)

    async def _get_or_create_pipeline_for_submit(
        self,
        config: PipelineConfig,
        output_split_id: str,
        task_type: str,
        split: str,
    ) -> "Pipeline":
        """
        submit_pipeline 호환용 Pipeline get-or-create (v7.10, 027 §12-1 임시).

        §12-1 "저장/실행 분리" UX 가 §9-3 에서 정식 반영되기 전까지, 기존 "에디터에서 실행"
        경로가 그대로 동작하도록 Pipeline 엔티티를 자동 get-or-create 한다. §12-2 네이밍
        규칙에 맞춰 `{config.name}_{split.lower()}` 로 자동 생성. 동일 이름 Pipeline 이 이미
        있으면 재사용 (version='1.0' 고정). config.name / split 이 바뀌면 새 Pipeline 이
        만들어짐 — 사용자 명시적 의도는 없지만 legacy 흐름 호환을 위한 임시 정책.

        TODO §9-3: "저장" 엔드포인트 분리 시 이 함수는 제거하고 사용자 명시 create 로 대체.
        """
        from app.models.all_models import Pipeline

        base_name = f"{config.name}_{split.lower()}"
        result = await self.db.execute(
            select(Pipeline).where(
                Pipeline.name == base_name, Pipeline.version == "1.0",
            )
        )
        existing = result.scalars().first()
        if existing is not None:
            return existing

        pipeline = Pipeline(
            id=str(uuid.uuid4()),
            name=base_name,
            version="1.0",
            description=config.description,
            output_split_id=output_split_id,
            config=config.model_dump(),
            task_type=task_type,
            is_active=True,
        )
        self.db.add(pipeline)
        await self.db.flush()
        logger.info(
            "Pipeline 자동 생성 (submit_pipeline 호환)",
            pipeline_id=pipeline.id, name=base_name, task_type=task_type,
        )
        return pipeline

    async def _extract_resolved_input_versions(
        self, config: PipelineConfig,
    ) -> dict[str, str]:
        """
        config 가 참조하는 source split 들의 **현재 최신 READY 버전** 을 `{split_id: version}`
        으로 반환 (v7.10). submit_pipeline 호환 경로에서 자동 기본값 생성용.

        §4-2 schema_version 분기:
          v2 — config.get_all_source_split_ids() 로 split_id 직접
          v1 — dataset_version_id 들을 DB 에서 조회해 split_id 로 해석 (legacy 경로)

        두 경우 모두 마지막에 "split_id 별 최신 READY 버전" 을 DB 에서 조회한다.
        submit_run_from_pipeline 은 사용자가 선택한 resolved_input_versions 를 그대로
        받으므로 이 함수를 거치지 않음.
        """
        if config.is_schema_v2:
            split_ids: set[str] = set(config.get_all_source_split_ids())
        else:
            dataset_version_ids = config.get_all_source_dataset_ids()
            if not dataset_version_ids:
                return {}
            rs = await self.db.execute(
                select(DatasetVersion)
                .where(DatasetVersion.id.in_(dataset_version_ids))
                .options(selectinload(DatasetVersion.split_slot))
            )
            split_ids = {v.split_slot.id for v in rs.scalars().all()}

        if not split_ids:
            return {}

        # 각 split 의 최신 READY 버전 수집
        result = await self.db.execute(
            select(DatasetVersion)
            .where(
                DatasetVersion.split_id.in_(split_ids),
                DatasetVersion.status == "READY",
            )
            .order_by(DatasetVersion.split_id, DatasetVersion.created_at.desc())
        )
        latest: dict[str, str] = {}
        for dv in result.scalars().all():
            if dv.split_id not in latest:
                latest[dv.split_id] = dv.version
        return latest

    def _substitute_v2_to_resolved_config(
        self,
        config_dict: dict[str, Any],
        split_to_dataset_version_id: dict[str, str],
    ) -> dict[str, Any]:
        """
        v7.10 schema_version=2 config 의 `source:<split_id>` 참조를 실제 선택된
        `source:<dataset_version_id>` 로 치환한 **resolved** dict 반환.

        이 치환된 dict 가:
          - `PipelineRun.transform_config` 스냅샷으로 저장되고 (027 §2-2 의 "실행 시점
            최종 config 스냅샷 · resolved version 포함"),
          - Celery `run_pipeline` 태스크에 전달되어 기존 executor (v1 형식 assume) 가
            변경 없이 돌게 한다.

        v1 config 이거나 schema_version 이 없으면 deep copy 만 반환 (no-op).
        순수 파이썬 — DB 접근 없음.
        """
        import copy
        resolved = copy.deepcopy(config_dict)
        if resolved.get("schema_version") != 2:
            return resolved

        # tasks[*].inputs 치환
        for task_config in (resolved.get("tasks") or {}).values():
            inputs = task_config.get("inputs") or []
            new_inputs: list[str] = []
            for inp in inputs:
                if inp.startswith("source:"):
                    split_id = inp[len("source:"):]
                    dataset_version_id = split_to_dataset_version_id.get(split_id)
                    if dataset_version_id:
                        new_inputs.append(f"source:{dataset_version_id}")
                    else:
                        # resolved 가 부족하면 원본 유지 — executor 에서 에러 날 가능성
                        new_inputs.append(inp)
                else:
                    new_inputs.append(inp)
            task_config["inputs"] = new_inputs

        # v2 passthrough_source_split_id → v1 passthrough_source_dataset_id 치환
        passthrough_split_id = resolved.get("passthrough_source_split_id")
        if passthrough_split_id:
            dataset_version_id = split_to_dataset_version_id.get(passthrough_split_id)
            if dataset_version_id:
                resolved["passthrough_source_dataset_id"] = dataset_version_id

        return resolved

    async def _get_or_create_split(
        self, group_id: str, split: str,
    ) -> DatasetSplit:
        """
        (group_id, split) 정적 슬롯 조회/생성 (v7.9 3계층 분리).
        dataset_service._get_or_create_split 과 동일한 시맨틱.
        """
        split_upper = split.upper()
        existing = await self.db.execute(
            select(DatasetSplit).where(
                DatasetSplit.group_id == group_id,
                DatasetSplit.split == split_upper,
            )
        )
        split_obj = existing.scalar_one_or_none()
        if split_obj is not None:
            return split_obj

        split_obj = DatasetSplit(
            id=str(uuid.uuid4()),
            group_id=group_id,
            split=split_upper,
        )
        self.db.add(split_obj)
        await self.db.flush()
        return split_obj

    async def _next_version(self, split_id: str) -> str:
        """
        해당 split_id(DatasetSplit)의 다음 버전을 자동 계산한다 (v7.9).

        버전 정책: {major}.{minor}
        - major: 사용자가 명시적으로 파이프라인을 실행할 때 증가
        - minor: 향후 automation이 파이프라인을 자동 실행할 때 증가 (미구현)
        파이프라인 실행은 사용자 주도이므로 major를 올린다.
        """
        result = await self.db.execute(
            select(DatasetVersion.version)
            .where(DatasetVersion.split_id == split_id)
            .order_by(DatasetVersion.created_at.desc())
            .limit(1)
        )
        last_version = result.scalar_one_or_none()
        if not last_version:
            return "1.0"

        try:
            parts = last_version.lstrip("v").split(".")
            major = int(parts[0]) + 1
            return f"{major}.0"
        except (IndexError, ValueError):
            return "1.0"

    # ═════════════════════════════════════════════════════════════════════════
    # Pipeline 엔티티 CRUD (v7.10, 027 §2-1 / §12)
    # ═════════════════════════════════════════════════════════════════════════

    async def list_pipelines(
        self,
        *,
        include_inactive: bool = False,
        name_filter: str | None = None,
        task_type_filter: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Pipeline], int]:
        """
        Pipeline 목록 + 총 개수. 기본은 `is_active=TRUE` 만 (§5-3 legacy 숨기기 기본 ON).

        정렬 기준: name ASC, version DESC (같은 name 안에서 최신 version 이 위로).
        §3-4 "과거 run 복원 시 (name, version) 한 눈에 보임" 원칙 반영.
        """
        filters = []
        if not include_inactive:
            filters.append(Pipeline.is_active == True)  # noqa: E712
        if name_filter:
            filters.append(Pipeline.name.ilike(f"%{name_filter}%"))
        if task_type_filter:
            filters.append(Pipeline.task_type.in_(task_type_filter))

        base = select(Pipeline)
        for flt in filters:
            base = base.where(flt)

        total_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = int(total_result.scalar() or 0)

        items_query = (
            base
            .options(
                selectinload(Pipeline.output_split).selectinload(DatasetSplit.group),
                selectinload(Pipeline.automation),
            )
            .order_by(Pipeline.name.asc(), Pipeline.version.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(items_query)
        return list(result.scalars().all()), total

    async def get_pipeline(self, pipeline_id: str) -> Pipeline | None:
        """Pipeline 단건 조회 — output_split / automation 선로드."""
        result = await self.db.execute(
            select(Pipeline)
            .options(
                selectinload(Pipeline.output_split).selectinload(DatasetSplit.group),
                selectinload(Pipeline.automation),
            )
            .where(Pipeline.id == pipeline_id)
        )
        return result.scalars().first()

    async def update_pipeline(
        self,
        pipeline_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
    ) -> Pipeline | None:
        """
        Pipeline 편집 (§6-1 config immutable — config 는 받지 않음).

        `is_active` 를 False 로 전환 시 연결된 PipelineAutomation 이 있으면 error
        상태 + error_reason='PIPELINE_DELETED' 로 전환 (§6-4 (a)/(b) 중 기본 처리).
        """
        pipeline = await self.get_pipeline(pipeline_id)
        if pipeline is None:
            return None
        if name is not None:
            pipeline.name = name
        if description is not None:
            pipeline.description = description
        if is_active is not None and is_active != pipeline.is_active:
            pipeline.is_active = is_active
            if not is_active:
                await self._mark_automation_as_pipeline_deleted(pipeline.id)
        await self.db.flush()
        return pipeline

    async def _mark_automation_as_pipeline_deleted(self, pipeline_id: str) -> None:
        """Pipeline soft delete 시 active automation 의 상태를 error 로 전환 (§6-4)."""
        result = await self.db.execute(
            select(PipelineAutomation)
            .where(
                PipelineAutomation.pipeline_id == pipeline_id,
                PipelineAutomation.is_active == True,  # noqa: E712
            )
        )
        for automation in result.scalars().all():
            automation.status = "error"
            automation.error_reason = "PIPELINE_DELETED"
        await self.db.flush()

    async def count_runs_by_pipeline(
        self, pipeline_ids: list[str],
    ) -> dict[str, tuple[int, Any]]:
        """
        pipeline_id 별 run_count + last_run_at 집계.

        목록 UI 에서 Pipeline 각 행에 실행 횟수 / 최근 실행 시각 노출용. 빈 dict 반환
        시 모든 Pipeline 은 0 / None 으로 간주.
        """
        if not pipeline_ids:
            return {}
        result = await self.db.execute(
            select(
                PipelineRun.pipeline_id,
                func.count(PipelineRun.id).label("run_count"),
                func.max(PipelineRun.created_at).label("last_run_at"),
            )
            .where(PipelineRun.pipeline_id.in_(pipeline_ids))
            .group_by(PipelineRun.pipeline_id)
        )
        return {
            row.pipeline_id: (int(row.run_count), row.last_run_at)
            for row in result.all()
        }

    async def list_runs_by_pipeline(
        self,
        pipeline_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PipelineRun], int]:
        """특정 Pipeline 에 속하는 PipelineRun 목록. 최신순."""
        base = select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id)
        total_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = int(total_result.scalar() or 0)
        result = await self.db.execute(
            base
            .options(
                selectinload(PipelineRun.output_dataset)
                .selectinload(DatasetVersion.split_slot)
                .selectinload(DatasetSplit.group)
            )
            .order_by(PipelineRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    # ═════════════════════════════════════════════════════════════════════════
    # PipelineRun 제출 (Pipeline 기반 — 027 §4-3 Version Resolver)
    # ═════════════════════════════════════════════════════════════════════════

    async def submit_run_from_pipeline(
        self,
        pipeline_id: str,
        resolved_input_versions: dict[str, str],
    ) -> PipelineSubmitResponse:
        """
        `POST /pipelines/{id}/runs` 구현. Version Resolver Modal 이 확정한
        `{split_id: version}` 을 받아 PipelineRun 1건을 생성하고 Celery dispatch.

        legacy Pipeline (is_active=FALSE) 은 차단 (§5-3).

        본 메서드는 §12-5 기준 "실행 시점" 에 해당하므로 validate_runtime 성격의
        최소 체크만 수행 (현 단계 §9-3 에서는 structural 재검증은 수행하지 않음 — 저장
        시점에 이미 통과했다고 가정. §9-4 FE DataLoad 축소 시 저장 경로가 생기면 재검토).
        """
        pipeline = await self.get_pipeline(pipeline_id)
        if pipeline is None:
            raise ValueError(f"Pipeline not found: {pipeline_id}")
        if not pipeline.is_active:
            raise ValueError(
                "Pipeline 이 비활성(legacy 또는 soft-deleted) 이라 새 run 을 제출할 수 없습니다. "
                "새 버전을 만들어 실행하거나 is_active=True 로 복원하세요."
            )

        # config 에서 PipelineConfig Pydantic 복원 (실행 파이프라인의 진짜 스펙)
        config = PipelineConfig(**pipeline.config)

        # output 스키마 결정 — Pipeline.output_split 기준으로 그룹 / split 재사용
        output_split_slot = pipeline.output_split
        output_group = output_split_slot.group if output_split_slot else None
        if output_group is None:
            raise ValueError(
                "Pipeline 의 output_split / group 이 해석되지 않았습니다. "
                "Pipeline 상세를 확인하세요."
            )

        # v7.10 §9-9 fix: 사용자가 output 그룹을 외부에서 soft-delete 한 상태에서 재실행
        # 한 경우, 그룹을 자동 복구한다. Pipeline 의 output_split FK 가 이 그룹을
        # 가리키므로 의미상 "Pipeline 이 살아있으면 output 그룹도 살아있어야" 한다.
        # 그렇지 않으면 새 dataset_version 만 deleted 그룹에 추가되어 목록에 안 나타나고
        # task_types 도 NULL 인 채로 남는다.
        if output_group.deleted_at is not None:
            logger.info(
                "soft-deleted output 그룹 자동 복구 (재실행 트리거)",
                group_id=output_group.id, group_name=output_group.name,
            )
            output_group.deleted_at = None

        # task_types 백필 — 신규 그룹이 처음 만들어질 때 source 교집합으로 채워졌어야
        # 했는데 누락된 케이스 (예: 과거 v1/v2 분기 버그). 매 실행 시 source 교집합을
        # 재계산해 빈 경우만 채운다.
        if not output_group.task_types:
            inferred_task_types = await self._intersect_source_task_types(config)
            if inferred_task_types:
                output_group.task_types = inferred_task_types
                logger.info(
                    "output 그룹 task_types 자동 백필",
                    group_id=output_group.id, task_types=inferred_task_types,
                )

        # 실행 시점 runtime 검증: resolved_input_versions 에 모든 source split 이 있는지.
        # §4-2 schema_version 분기:
        #   v2 (source:<split_id>) — split_id 직접 추출
        #   v1 (source:<dataset_version_id>) — dataset_version_id 를 split_id 로 해석
        #     (legacy 경로이고 Pipeline.is_active=FALSE 라 실제로 도달하지 않음)
        if config.is_schema_v2:
            expected_split_ids = set(config.get_all_source_split_ids())
        else:
            expected_split_ids = await self._resolve_expected_input_split_ids(
                config.get_all_source_dataset_ids()
            )
        missing = expected_split_ids - set(resolved_input_versions.keys())
        if missing:
            raise ValueError(
                f"resolved_input_versions 에 다음 split_id 가 누락되었습니다: {sorted(missing)}"
            )

        # resolved_input_versions → 실행 시점의 dataset_version_id 매핑 (runtime 의미)
        runtime_dataset_ids = await self._resolve_versions_to_dataset_ids(
            resolved_input_versions
        )

        # output 버전 자동 증가 (§9-5 manual 실행 = major++ 유지, §9-4 에서 automation/manual 분기 예정)
        version = await self._next_version(output_split_slot.id)
        logger.info(
            "Pipeline run 제출 시작",
            pipeline_id=pipeline.id, pipeline_name=pipeline.name,
            output_group=output_group.name, split=output_split_slot.split,
            new_version=version,
        )

        # storage_uri 사전 생성 (submit_pipeline 와 동일 패턴)
        dataset_type = output_group.dataset_type
        annotation_format = (
            config.output.annotation_format.upper()
            if config.output.annotation_format else output_group.annotation_format
        )
        storage_uri = self.storage.build_dataset_uri(
            dataset_type=dataset_type,
            name=output_group.name,
            split=output_split_slot.split,
            version=version,
        )

        # DatasetVersion 생성 (status=PENDING)
        dataset = DatasetVersion(
            id=str(uuid.uuid4()),
            split_id=output_split_slot.id,
            version=version,
            annotation_format=annotation_format,
            storage_uri=storage_uri,
            status="PENDING",
        )
        self.db.add(dataset)
        await self.db.flush()

        # PipelineRun 생성 — Pipeline.config 는 v2 (split_id) 템플릿이므로, 실행 시점에
        # source:<split_id> → source:<dataset_version_id> 로 치환한 resolved dict 를
        # transform_config 에 저장 (027 §2-2 "실행 시점 최종 config 스냅샷 · resolved
        # version 포함"). Celery executor 는 이 resolved dict 로 기존 v1 경로를 돈다.
        resolved_config_dict = self._substitute_v2_to_resolved_config(
            pipeline.config, runtime_dataset_ids,
        )
        run = PipelineRun(
            id=str(uuid.uuid4()),
            pipeline_id=pipeline.id,
            automation_id=None,
            output_dataset_id=dataset.id,
            transform_config=resolved_config_dict,
            resolved_input_versions=resolved_input_versions,
            trigger_kind="manual_from_editor",
            status="PENDING",
        )
        self.db.add(run)
        await self.db.flush()

        # Celery dispatch — resolved dict (v1 형식) 을 executor 에 전달
        from app.tasks.pipeline_tasks import run_pipeline
        celery_result = run_pipeline.delay(run.id, resolved_config_dict)
        run.celery_task_id = celery_result.id
        await self.db.flush()

        logger.info(
            "Pipeline run 디스패치 완료",
            pipeline_id=pipeline.id, run_id=run.id,
            celery_task_id=run.celery_task_id,
            input_versions=resolved_input_versions,
            runtime_dataset_ids=runtime_dataset_ids,
        )

        return PipelineSubmitResponse(
            execution_id=run.id,
            celery_task_id=run.celery_task_id,
            message="파이프라인 실행이 제출되었습니다.",
        )

    async def _resolve_expected_input_split_ids(
        self, dataset_version_ids: list[str],
    ) -> set[str]:
        """
        Pipeline.config (schema v1) 의 source:<dataset_version_id> 들을 split_id 집합으로.

        Version Resolver 가 resolved_input_versions 로 채워야 하는 split 의 기대 집합.
        """
        if not dataset_version_ids:
            return set()
        result = await self.db.execute(
            select(DatasetVersion)
            .where(DatasetVersion.id.in_(dataset_version_ids))
            .options(selectinload(DatasetVersion.split_slot))
        )
        return {v.split_slot.id for v in result.scalars().all()}

    async def _resolve_versions_to_dataset_ids(
        self, resolved_input_versions: dict[str, str],
    ) -> dict[str, str]:
        """
        `{split_id: version}` → `{split_id: dataset_version_id}`. READY 상태 검증 포함.

        존재하지 않거나 READY 아닌 version 이 있으면 ValueError. 실행 시점 방어.
        """
        if not resolved_input_versions:
            return {}
        split_ids = list(resolved_input_versions.keys())
        result = await self.db.execute(
            select(DatasetVersion)
            .where(DatasetVersion.split_id.in_(split_ids))
        )
        by_split: dict[str, list[DatasetVersion]] = {}
        for dv in result.scalars().all():
            by_split.setdefault(dv.split_id, []).append(dv)

        resolved: dict[str, str] = {}
        for split_id, version in resolved_input_versions.items():
            candidates = [dv for dv in by_split.get(split_id, []) if dv.version == version]
            if not candidates:
                raise ValueError(
                    f"DatasetVersion 을 찾을 수 없음 (split_id={split_id}, version={version})"
                )
            dataset_version = candidates[0]
            if dataset_version.status != "READY":
                raise ValueError(
                    f"DatasetVersion 이 READY 상태가 아님 (id={dataset_version.id}, "
                    f"status={dataset_version.status})"
                )
            resolved[split_id] = dataset_version.id
        return resolved
