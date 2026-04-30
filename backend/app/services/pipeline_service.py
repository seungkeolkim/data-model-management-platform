"""
파이프라인 실행 서비스.

파이프라인 제출(submit) → Celery 태스크 디스패치, 실행 상태 조회 등을 처리한다.
"""
from __future__ import annotations

import random
import uuid
from typing import Any


def _random_family_color() -> str:
    """가독성 좋은 mid-tone 랜덤 hex (각 채널 80~200) — Family 자동 색상 할당."""
    return "#{:02x}{:02x}{:02x}".format(
        random.randint(80, 200),
        random.randint(80, 200),
        random.randint(80, 200),
    )

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
    PipelineFamily,
    PipelineRun,
    PipelineVersion,
)
from app.schemas.pipeline import PipelineSaveResponse, PipelineSubmitResponse
from lib.pipeline.config import (
    SOURCE_TYPE_SPLIT,
    SOURCE_TYPE_VERSION,
    PartialPipelineConfig,
    PipelineConfig,
    parse_source_ref,
)
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

        검증 항목:
          - source:<split_id> 참조의 DatasetSplit 존재 / 상위 group soft-delete 여부
          - cls_merge / cls_set_head_labels / cls_filter_by_class / output_schema 호환성
            (head_schema 는 group 레벨 SSOT 이므로 source 가 healthy 한 후에만 수행)
        """
        result = PipelineValidationResult()

        # 모든 source split 수집 (태스크별로 추적하여 field 정보 제공)
        for task_name, task_config in config.tasks.items():
            for split_id in task_config.get_source_split_ids():
                await self._validate_source_split_ref(split_id, task_name, result)

        # Passthrough 모드(tasks 비어있음)에서도 소스 검증
        if config.is_passthrough and config.passthrough_source_split_id:
            await self._validate_source_split_ref(
                config.passthrough_source_split_id, "__passthrough__", result,
            )

        # 상류/출력 head_schema 호환성 — source 검증이 먼저 통과한 경우에만 수행.
        if result.is_valid:
            await self._validate_cls_merge_compatibility(config, result)
            await self._validate_cls_set_head_labels_compatibility(config, result)
            await self._validate_cls_filter_by_class_compatibility(config, result)
            await self._validate_output_schema_compatibility(config, result)

        return result

    async def _validate_source_split_ref(
        self,
        split_id: str,
        task_name: str,
        result: PipelineValidationResult,
    ) -> None:
        """
        단일 `source:<split_id>` 참조에 대한 저장 시점 검증.
          - DatasetSplit 존재
          - 상위 DatasetGroup 이 soft-delete 되지 않음

        실제 version 선택 및 READY 상태 체크는 실행 시점 Version Resolver 에서.
        """
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

    async def _build_source_meta_map(
        self, config: PipelineConfig,
    ) -> dict[str, Any]:
        """
        config 의 모든 source ref 에 대해 head_schema 기반 stub meta 를 생성 (v7.10).

        반환 dict 의 key = source split_id. 4개 validator (cls_merge /
        cls_set_head_labels / cls_filter_by_class / output_schema_compatibility) 가
        동일한 key 로 meta 를 조회한다.

        head_schema 는 group 레벨 SSOT 이므로 version 무관 — split → group 만 거슬러
        올라가면 충분.
        """
        from lib.pipeline.schema_preview import build_stub_source_meta

        meta_map: dict[str, Any] = {}
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
                dataset_id=split_obj.id,  # stub 인터페이스 호환 — key 는 split_id
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

        # source head_schema stub meta 미리 로드 — 공통 헬퍼
        source_meta_by_dataset_id = await self._build_source_meta_map(config)

        for task_name, task_config in cls_merge_tasks:
            input_head_schemas: list[Any] = []
            for ref in task_config.inputs:
                if ref.startswith("source:"):
                    source_dataset_id = parse_source_ref(ref)[1]
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
                source_dataset_id = parse_source_ref(upstream_ref)[1]
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
                source_dataset_id = parse_source_ref(upstream_ref)[1]
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
        # classification 소스가 없으면 passthrough/preview 모두 head_schema=None 을
        # 리턴해 아래 분기에서 자연 처리.
        source_meta_by_dataset_id = await self._build_source_meta_map(config)

        passthrough_source_ref = (
            config.passthrough_source_split_id if config.is_passthrough else None
        )

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
    # 파이프라인 저장 (§12-1 저장/실행 분리)
    # -------------------------------------------------------------------------

    async def save_pipeline_from_config(
        self,
        config: PipelineConfig,
        *,
        concept_name: str | None = None,
    ) -> PipelineSaveResponse:
        """
        에디터 config 를 Pipeline (concept) + PipelineVersion 으로 저장.

        설계서 §12-1 "저장/실행 분리" 의 정식 진입점. 실행은 분리된 흐름:
          - 목록 행 우측 "실행" 버튼 → Version Resolver Modal
          - `POST /pipelines/versions/{id}/runs`

        저장 단계의 책임:
          1. 출력 DatasetGroup 조회/생성 (없으면 신규 — §12-7 빈 그룹 노출 OK)
          2. 출력 DatasetSplit 슬롯 조회/생성 (정적 슬롯)
          3. Pipeline (concept) + PipelineVersion 조회/생성:
             - 동일 name 의 concept 가 없으면 신규 + version "1.0"
             - 있으면 최신 version 의 config 와 비교 — 동일하면 재사용, 다르면
               major++ 신규 version
        DatasetVersion / PipelineRun 은 만들지 않는다 (실행 시점 책임).

        Args:
            concept_name: 사용자가 저장 모달에서 직접 입력한 Pipeline (concept) 이름.
                None 이면 §12-2 자동 규칙 (`{config.name}_{split.lower()}`) 으로 생성.
                동일 name 이 있으면 기존 concept 재사용 + 새 version 추가 (현 동작 유지).
        """
        dataset_type = config.output.dataset_type.upper()
        annotation_format = config.output.annotation_format.upper()
        split = config.output.split.upper()

        # ── 소스 task_types 교집합 ──
        source_task_types = await self._intersect_source_task_types(config)

        # ── 출력 DatasetGroup 조회/생성 (§12-7) ──
        group = await self._find_or_create_dataset_group(
            name=config.name,
            dataset_type=dataset_type,
            annotation_format=annotation_format,
            task_types=source_task_types,
        )

        # ── 출력 DatasetSplit 슬롯 조회/생성 (정적 슬롯) ──
        split_slot = await self._get_or_create_split(group.id, split)

        # ── Pipeline (concept) + PipelineVersion 저장 ──
        pipeline_task_type = source_task_types[0] if source_task_types else "DETECTION"
        pipeline, version_obj, is_new_concept, is_new_version = (
            await self._save_concept_and_version(
                config=config,
                output_split_id=split_slot.id,
                task_type=pipeline_task_type,
                split=split,
                concept_name=concept_name,
            )
        )

        if is_new_concept:
            user_message = (
                f"Pipeline '{pipeline.name}' 을(를) 새로 저장했습니다 "
                f"(v{version_obj.version})."
            )
        elif is_new_version:
            user_message = (
                f"기존 Pipeline '{pipeline.name}' 에 새 버전 v{version_obj.version} "
                "이(가) 추가되었습니다."
            )
        else:
            user_message = (
                f"동일 config 로 저장된 기존 버전 v{version_obj.version} 을(를) 재사용합니다."
            )

        logger.info(
            "Pipeline 저장 완료",
            pipeline_id=pipeline.id, pipeline_name=pipeline.name,
            version_id=version_obj.id, version=version_obj.version,
            is_new_concept=is_new_concept, is_new_version=is_new_version,
        )

        return PipelineSaveResponse(
            pipeline_id=pipeline.id,
            pipeline_version_id=version_obj.id,
            pipeline_name=pipeline.name,
            version=version_obj.version,
            is_new_concept=is_new_concept,
            is_new_version=is_new_version,
            message=user_message,
        )

    # -------------------------------------------------------------------------
    # 실행 상태 조회
    # -------------------------------------------------------------------------

    async def get_execution_status(self, execution_id: str) -> PipelineRun | None:
        """PipelineRun 단건 조회 (output_dataset + group + pipeline_version 선로드)."""
        result = await self.db.execute(
            select(PipelineRun)
            .options(
                selectinload(PipelineRun.output_dataset)
                .selectinload(DatasetVersion.split_slot)
                .selectinload(DatasetSplit.group),
                selectinload(PipelineRun.pipeline_version)
                .selectinload(PipelineVersion.pipeline),
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
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[PipelineRun], int]:
        """PipelineRun 목록 조회 — 페이지네이션 + 사용자 지정 정렬.

        지원 sort_by 키:
            created_at / started_at / finished_at / status — PipelineRun 자체 컬럼
            pipeline_name / pipeline_version              — Pipeline / PipelineVersion join
            output_dataset_group_name / output_dataset_split / output_dataset_version
                                                          — DatasetGroup / Split / Version join

        join 이 필요한 키는 outerjoin (LEFT JOIN) 으로 묶어 정렬한다 — 누락된 row 도 NULL
        로 끝에 모이도록.
        """
        # ── 정렬 표현식 + 필요한 join 결정 ──
        sort_order_normalized = sort_order.lower() if sort_order else "desc"
        is_desc = sort_order_normalized != "asc"

        sort_expr = None
        join_kind: str | None = None  # "pipeline" 또는 "output" 또는 None
        if sort_by == "status":
            sort_expr = PipelineRun.status
        elif sort_by == "started_at":
            sort_expr = PipelineRun.started_at
        elif sort_by == "finished_at":
            sort_expr = PipelineRun.finished_at
        elif sort_by == "pipeline_name":
            sort_expr = Pipeline.name
            join_kind = "pipeline"
        elif sort_by == "pipeline_version":
            sort_expr = PipelineVersion.version
            join_kind = "pipeline"
        elif sort_by == "output_dataset_group_name":
            sort_expr = DatasetGroup.name
            join_kind = "output"
        elif sort_by == "output_dataset_split":
            sort_expr = DatasetSplit.split
            join_kind = "output"
        elif sort_by == "output_dataset_version":
            sort_expr = DatasetVersion.version
            join_kind = "output"
        else:
            # 기본값 + 알 수 없는 키는 created_at 으로 fallback
            sort_expr = PipelineRun.created_at

        base_query = select(PipelineRun)
        if join_kind == "pipeline":
            base_query = base_query.outerjoin(
                PipelineVersion,
                PipelineRun.pipeline_version_id == PipelineVersion.id,
            ).outerjoin(
                Pipeline, PipelineVersion.pipeline_id == Pipeline.id,
            )
        elif join_kind == "output":
            base_query = base_query.outerjoin(
                DatasetVersion,
                PipelineRun.output_dataset_id == DatasetVersion.id,
            ).outerjoin(
                DatasetSplit, DatasetVersion.split_id == DatasetSplit.id,
            ).outerjoin(
                DatasetGroup, DatasetSplit.group_id == DatasetGroup.id,
            )

        # count 는 join 영향 없이 PipelineRun.id 기반으로 안정적으로 산출
        total = await self.db.scalar(select(func.count(PipelineRun.id))) or 0

        # 1순위 = 사용자 정렬 컬럼, 2순위 = 동일 값 안정화용 created_at desc
        primary_clause = sort_expr.desc() if is_desc else sort_expr.asc()
        order_clauses = [primary_clause]
        if sort_by != "created_at":
            order_clauses.append(PipelineRun.created_at.desc())

        list_query = (
            base_query
            .options(
                selectinload(PipelineRun.output_dataset)
                .selectinload(DatasetVersion.split_slot)
                .selectinload(DatasetSplit.group),
                selectinload(PipelineRun.pipeline_version)
                .selectinload(PipelineVersion.pipeline),
            )
            .order_by(*order_clauses)
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

        # 1) 파이프라인에서 참조하는 모든 source split 의 head_schema + task_types 를 DB 에서 로드.
        #    task_ 분기에서 그룹 판정에 사용.
        source_meta_by_dataset_id: dict[str, object] = {}
        source_task_types_by_dataset_id: dict[str, list[str]] = {}

        for split_id in config.get_all_source_split_ids():
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

        # 2) target_ref 분기.
        #
        # source:<id> 타겟은 config 참조 여부와 무관하게 해당 dataset 의
        # head_schema 를 DB 에서 직접 읽어 반환한다. dataLoad 노드 단독으로
        # 선택된 경우 (config.tasks 와 passthrough 가 비어 있어 해당 source 가
        # source_meta_by_dataset_id 에 포함되지 않을 수 있다) 에도 프리뷰가
        # 정상 동작하도록 하기 위함.
        if target_ref.startswith("source:"):
            source_split_id = parse_source_ref(target_ref)[1]
            source_meta = source_meta_by_dataset_id.get(source_split_id)
            group_task_types = source_task_types_by_dataset_id.get(source_split_id)
            if source_meta is None:
                # config 에 참조되지 않은 source — dataLoad 단독 선택 등.
                # split → group 직접 로드.
                split_row = await self.db.execute(
                    select(DatasetSplit)
                    .options(selectinload(DatasetSplit.group))
                    .where(DatasetSplit.id == source_split_id)
                )
                split_obj = split_row.scalar_one_or_none()
                if split_obj is None:
                    return {
                        "task_kind": "unknown",
                        "head_schema": None,
                        "error_code": "SOURCE_NOT_FOUND",
                        "error_message": (
                            f"source split_id='{source_split_id}' 를 DB 에서 찾을 수 없습니다."
                        ),
                    }
                group_obj = split_obj.group
                group_head_schema = group_obj.head_schema if group_obj else None
                group_task_types = group_obj.task_types if group_obj else None
                source_meta = build_stub_source_meta(
                    dataset_id=source_split_id,
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
        파이프라인 config 의 소스 split 들이 속한 그룹들의 task_types 교집합 반환.
        소스가 없거나 교집합이 비어 있으면 None.
        """
        split_ids: set[str] = set(config.get_all_source_split_ids())
        if not split_ids:
            return None
        result = await self.db.execute(
            select(DatasetGroup.task_types)
            .join(DatasetSplit, DatasetSplit.group_id == DatasetGroup.id)
            .where(DatasetSplit.id.in_(split_ids))
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

    async def _save_concept_and_version(
        self,
        config: PipelineConfig,
        output_split_id: str,
        task_type: str,
        split: str,
        *,
        concept_name: str | None = None,
    ) -> tuple["Pipeline", "PipelineVersion", bool, bool]:
        """
        Pipeline (concept) 와 PipelineVersion 을 저장 (§12-1 저장/실행 분리의 핵심 헬퍼).

        규칙:
          - 개념명: 사용자가 명시한 `concept_name` 또는 자동 `{config.name}_{split.lower()}`
            (§12-2 — 전역 UNIQUE). 동일 name 이 이미 있으면 같은 concept 로 재사용
            + 새 version 추가 (사용자가 의도적으로 같은 이름을 입력해 새 버전을
            올리는 경우 자연스러운 동작).
          - Pipeline 이 없으면 생성 (family_id=NULL, output_split / task_type 고정).
          - 있으면 최신 version 의 config 와 JSON 평탄 비교 — 동일하면 재사용,
            다르면 major++ 신규 version.

        Returns:
            (pipeline, pipeline_version, is_new_concept, is_new_version) 튜플.
            is_new_concept = True 이면 Pipeline 행이 새로 생성됨.
            is_new_version = True 이면 PipelineVersion 행이 새로 생성됨.
        """
        import json

        # 사용자가 명시한 이름이 있으면 strip 후 사용. 없으면 자동 규칙.
        if concept_name is not None and concept_name.strip():
            base_name = concept_name.strip()
        else:
            base_name = f"{config.name}_{split.lower()}"
        existing_concept = (await self.db.execute(
            select(Pipeline)
            .options(selectinload(Pipeline.versions))
            .where(Pipeline.name == base_name)
        )).scalars().first()

        # 동일 이름이 존재하지만 output_split_id 가 다르면 차단 (§12-2 회색지대 방지).
        # 같은 이름 + 다른 출력은 부모 Pipeline.output_split 과 신규 version.config 의
        # output 이 어긋나 실행 시점에 모순되므로 저장 거부.
        if (
            existing_concept is not None
            and existing_concept.output_split_id != output_split_id
        ):
            raise ValueError(
                f"같은 이름의 Pipeline ('{base_name}') 이 이미 다른 output "
                "(group/split) 으로 등록돼 있습니다. 다른 이름을 사용하거나, "
                "출력을 동일하게 맞추세요."
            )

        new_config_dict = config.model_dump()
        new_config_json = json.dumps(new_config_dict, sort_keys=True, default=str)

        if existing_concept is None:
            concept = Pipeline(
                id=str(uuid.uuid4()),
                family_id=None,
                name=base_name,
                description=config.description,
                output_split_id=output_split_id,
                task_type=task_type,
                is_active=True,
            )
            self.db.add(concept)
            await self.db.flush()
            new_version = PipelineVersion(
                id=str(uuid.uuid4()),
                pipeline_id=concept.id,
                version="1.0",
                config=new_config_dict,
                is_active=True,
            )
            self.db.add(new_version)
            await self.db.flush()
            logger.info(
                "Pipeline + Version 신규 저장",
                pipeline_id=concept.id, version_id=new_version.id, name=base_name,
            )
            return concept, new_version, True, True

        # 동일 name 이 존재. 최신 version 비교.
        latest_version: PipelineVersion | None = None
        if existing_concept.versions:
            latest_version = sorted(
                existing_concept.versions,
                key=lambda v: v.created_at, reverse=True,
            )[0]

        if latest_version is not None:
            cached_json = json.dumps(
                latest_version.config, sort_keys=True, default=str,
            )
            if cached_json == new_config_json:
                # 동일 config — 재사용.
                return existing_concept, latest_version, False, False

        # config 변경 → 새 version (major++)
        next_version_str = self._next_pipeline_version_str(existing_concept.versions)
        new_version = PipelineVersion(
            id=str(uuid.uuid4()),
            pipeline_id=existing_concept.id,
            version=next_version_str,
            config=new_config_dict,
            is_active=True,
        )
        self.db.add(new_version)
        await self.db.flush()
        logger.info(
            "Pipeline 신규 Version 추가 (config 변경)",
            pipeline_id=existing_concept.id, version_id=new_version.id,
            new_version=next_version_str,
        )
        return existing_concept, new_version, False, True

    @staticmethod
    def _next_pipeline_version_str(versions: list[PipelineVersion]) -> str:
        """기존 PipelineVersion 들에서 다음 major.0 문자열 산출."""
        max_major = 0
        for v in versions:
            try:
                major = int(v.version.split(".")[0])
                if major > max_major:
                    max_major = major
            except (ValueError, IndexError):
                continue
        return f"{max_major + 1}.0"

    def _substitute_resolved_versions(
        self,
        config_dict: dict[str, Any],
        split_to_dataset_version_id: dict[str, str],
    ) -> dict[str, Any]:
        """
        config 의 `source:dataset_split:<split_id>` 토큰을 v3 resolved 포맷 인
        `source:dataset_version:<version_id>` 로 치환한 dict 반환.

        이 치환된 dict 가:
          - PipelineRun.transform_config 스냅샷으로 저장되고
          - Celery run_pipeline 태스크에 전달되어 executor 가 dataset_version_id 단위로
            데이터를 로드한다.

        순수 파이썬 — DB 접근 없음.
        """
        import copy
        resolved = copy.deepcopy(config_dict)

        # schema_version 은 v3 그대로 (포맷이 source 의 type 차원만 spec→resolved 로 바뀜).
        resolved.setdefault("schema_version", 3)

        # tasks[*].inputs 치환
        for task_config in (resolved.get("tasks") or {}).values():
            inputs = task_config.get("inputs") or []
            new_inputs: list[str] = []
            for inp in inputs:
                parsed = parse_source_ref(inp) if isinstance(inp, str) else None
                if parsed is None:
                    new_inputs.append(inp)
                    continue
                type_, id_ = parsed
                if type_ == SOURCE_TYPE_SPLIT:
                    dataset_version_id = split_to_dataset_version_id.get(id_)
                    if dataset_version_id:
                        new_inputs.append(
                            f"source:{SOURCE_TYPE_VERSION}:{dataset_version_id}"
                        )
                    else:
                        # resolved 누락 — 원본 유지해 executor 에서 명시적 에러 유도
                        new_inputs.append(inp)
                else:
                    # 이미 dataset_version 토큰 (이중 치환 방지) — 그대로 유지
                    new_inputs.append(inp)
            task_config["inputs"] = new_inputs

        # passthrough — split_id 를 resolved dataset_version_id 로 치환해 executor 로 전달
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
    # Pipeline (concept) CRUD — v7.11
    # ═════════════════════════════════════════════════════════════════════════

    async def list_pipelines(
        self,
        *,
        include_inactive: bool = False,
        name_filter: str | None = None,
        task_type_filter: list[str] | None = None,
        family_id: list[str] | None = None,
        family_unfiled: bool = False,
        output_split_id: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Pipeline], int]:
        """
        Pipeline (concept) 목록. 각 행은 versions / family / output_split 선로드.

        family_id / family_unfiled 다중 필터 (OR 결합):
            - family_id list 지정 → 해당 family 들 중 하나에 속하는 Pipeline
            - family_unfiled=True → family_id IS NULL 인 미분류 Pipeline 포함
            - 둘 다 비어있으면 → 필터 미적용 (전체 표시)

        output_split_id (다중 IN):
            - 지정된 split 중 하나를 output 으로 가진 Pipeline 만 반환.
            - 저장 모달의 "기존 Pipeline 선택" 모드에서 같은 (group, split) 출력
              Pipeline 만 후보로 제시할 때 사용 (§12-2 회색지대 차단 보조).
        """
        from sqlalchemy import or_

        filters = []
        if not include_inactive:
            filters.append(Pipeline.is_active == True)  # noqa: E712
        if name_filter:
            filters.append(Pipeline.name.ilike(f"%{name_filter}%"))
        if task_type_filter:
            filters.append(Pipeline.task_type.in_(task_type_filter))
        if output_split_id:
            filters.append(Pipeline.output_split_id.in_(output_split_id))
        if family_id or family_unfiled:
            family_or_clauses = []
            if family_id:
                family_or_clauses.append(Pipeline.family_id.in_(family_id))
            if family_unfiled:
                family_or_clauses.append(Pipeline.family_id.is_(None))
            filters.append(or_(*family_or_clauses))

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
                selectinload(Pipeline.family),
                selectinload(Pipeline.output_split).selectinload(DatasetSplit.group),
                selectinload(Pipeline.versions).selectinload(PipelineVersion.automation),
            )
            .order_by(Pipeline.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(items_query)
        return list(result.scalars().all()), total

    async def get_pipeline(self, pipeline_id: str) -> Pipeline | None:
        """Pipeline (concept) 단건 조회 — family / versions / output_split 선로드."""
        result = await self.db.execute(
            select(Pipeline)
            .options(
                selectinload(Pipeline.family),
                selectinload(Pipeline.output_split).selectinload(DatasetSplit.group),
                selectinload(Pipeline.versions).selectinload(PipelineVersion.automation),
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
        family_id: str | None = None,
        unset_family: bool = False,
        is_active: bool | None = None,
    ) -> Pipeline | None:
        """
        Pipeline (concept) 편집. config / version 은 PipelineVersion 영역.

        family_id 변경:
            - 새 family_id 지정 → 그 family 로 이동
            - unset_family=True → family_id NULL (미분류로)
            - 둘 다 미지정 → 변경 없음

        is_active=False 전환 시 모든 version 의 active automation 도 error 처리.
        """
        pipeline = await self.get_pipeline(pipeline_id)
        if pipeline is None:
            return None
        if name is not None:
            pipeline.name = name
        if description is not None:
            pipeline.description = description
        if unset_family:
            pipeline.family_id = None
        elif family_id is not None:
            pipeline.family_id = family_id
        if is_active is not None and is_active != pipeline.is_active:
            pipeline.is_active = is_active
            if not is_active:
                await self._mark_automation_as_pipeline_deleted(pipeline.id)
        await self.db.flush()
        return pipeline

    async def _mark_automation_as_pipeline_deleted(self, pipeline_id: str) -> None:
        """Pipeline soft delete 시, 모든 version 의 active automation 상태를 error 로 전환."""
        result = await self.db.execute(
            select(PipelineAutomation)
            .join(
                PipelineVersion,
                PipelineAutomation.pipeline_version_id == PipelineVersion.id,
            )
            .where(
                PipelineVersion.pipeline_id == pipeline_id,
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
        pipeline_id (concept) 별 run_count + last_run_at 집계.
        모든 version 의 run 을 합산.
        """
        if not pipeline_ids:
            return {}
        result = await self.db.execute(
            select(
                PipelineVersion.pipeline_id.label("pipeline_id"),
                func.count(PipelineRun.id).label("run_count"),
                func.max(PipelineRun.created_at).label("last_run_at"),
            )
            .join(
                PipelineRun,
                PipelineRun.pipeline_version_id == PipelineVersion.id,
            )
            .where(PipelineVersion.pipeline_id.in_(pipeline_ids))
            .group_by(PipelineVersion.pipeline_id)
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
        """특정 Pipeline (concept) 의 모든 version 에 걸친 PipelineRun 목록. 최신순."""
        base = (
            select(PipelineRun)
            .join(
                PipelineVersion,
                PipelineRun.pipeline_version_id == PipelineVersion.id,
            )
            .where(PipelineVersion.pipeline_id == pipeline_id)
        )
        total_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = int(total_result.scalar() or 0)
        result = await self.db.execute(
            base
            .options(
                selectinload(PipelineRun.output_dataset)
                .selectinload(DatasetVersion.split_slot)
                .selectinload(DatasetSplit.group),
                selectinload(PipelineRun.pipeline_version)
                .selectinload(PipelineVersion.pipeline),
            )
            .order_by(PipelineRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def list_runs_by_pipeline_version(
        self,
        pipeline_version_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PipelineRun], int]:
        """특정 PipelineVersion 에 속한 PipelineRun 목록. 최신순."""
        base = select(PipelineRun).where(
            PipelineRun.pipeline_version_id == pipeline_version_id
        )
        total_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = int(total_result.scalar() or 0)
        result = await self.db.execute(
            base
            .options(
                selectinload(PipelineRun.output_dataset)
                .selectinload(DatasetVersion.split_slot)
                .selectinload(DatasetSplit.group),
                selectinload(PipelineRun.pipeline_version)
                .selectinload(PipelineVersion.pipeline),
            )
            .order_by(PipelineRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    # ═════════════════════════════════════════════════════════════════════════
    # PipelineVersion CRUD (v7.11)
    # ═════════════════════════════════════════════════════════════════════════

    async def get_pipeline_version(
        self, pipeline_version_id: str,
    ) -> PipelineVersion | None:
        """PipelineVersion 단건 — pipeline.family / output_split / automation 선로드."""
        result = await self.db.execute(
            select(PipelineVersion)
            .options(
                selectinload(PipelineVersion.pipeline)
                .selectinload(Pipeline.family),
                selectinload(PipelineVersion.pipeline)
                .selectinload(Pipeline.output_split)
                .selectinload(DatasetSplit.group),
                selectinload(PipelineVersion.automation),
            )
            .where(PipelineVersion.id == pipeline_version_id)
        )
        return result.scalars().first()

    async def get_latest_active_version(
        self, pipeline_id: str,
    ) -> PipelineVersion | None:
        """Pipeline (concept) 의 최신 active version. 상세 페이지 기본 진입점."""
        result = await self.db.execute(
            select(PipelineVersion)
            .where(
                PipelineVersion.pipeline_id == pipeline_id,
                PipelineVersion.is_active == True,  # noqa: E712
            )
            .order_by(PipelineVersion.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def update_pipeline_version(
        self,
        pipeline_version_id: str,
        *,
        is_active: bool | None = None,
        description: str | None = None,
    ) -> PipelineVersion | None:
        """PipelineVersion 편집 — config 는 immutable. is_active / description 만 변경 가능.

        description 시맨틱:
            - None → 미변경
            - 빈 문자열 ("") → NULL 로 clear
            - 그 외 → 그 값으로 갱신
        """
        version = await self.get_pipeline_version(pipeline_version_id)
        if version is None:
            return None
        if is_active is not None and is_active != version.is_active:
            version.is_active = is_active
            if not is_active:
                # 이 version 에 매달린 active automation 도 error 처리
                if version.automation is not None:
                    version.automation.status = "error"
                    version.automation.error_reason = "PIPELINE_DELETED"
        if description is not None:
            version.description = description.strip() or None
        await self.db.flush()
        return version

    # ═════════════════════════════════════════════════════════════════════════
    # PipelineFamily CRUD (v7.11)
    # ═════════════════════════════════════════════════════════════════════════

    async def list_families(self) -> list[PipelineFamily]:
        """모든 Family. 정렬: name ASC. pipelines 선로드 (응답의 pipeline_count 산출용)."""
        result = await self.db.execute(
            select(PipelineFamily)
            .options(selectinload(PipelineFamily.pipelines))
            .order_by(PipelineFamily.name.asc())
        )
        return list(result.scalars().all())

    async def get_family(self, family_id: str) -> PipelineFamily | None:
        result = await self.db.execute(
            select(PipelineFamily)
            .options(selectinload(PipelineFamily.pipelines))
            .where(PipelineFamily.id == family_id)
        )
        return result.scalars().first()

    async def create_family(
        self,
        *,
        name: str,
        description: str | None = None,
        color: str | None = None,
    ) -> PipelineFamily:
        family = PipelineFamily(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            color=color or _random_family_color(),
        )
        self.db.add(family)
        await self.db.flush()
        # 응답 직렬화 시 family.pipelines 접근으로 MissingGreenlet 나지 않도록 선로드.
        # 신규 family 라 빈 리스트지만 lazy 트리거를 막아야 한다.
        result = await self.db.execute(
            select(PipelineFamily)
            .options(selectinload(PipelineFamily.pipelines))
            .where(PipelineFamily.id == family.id)
        )
        return result.scalars().first() or family

    async def update_family(
        self,
        family_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        color: str | None = None,
    ) -> PipelineFamily | None:
        family = await self.get_family(family_id)
        if family is None:
            return None
        if name is not None:
            family.name = name
        if description is not None:
            family.description = description
        if color is not None:
            family.color = color
        await self.db.flush()
        return family

    async def delete_family(self, family_id: str) -> bool:
        """Family hard delete. 자식 Pipeline 들의 family_id 는 ON DELETE SET NULL."""
        family = await self.get_family(family_id)
        if family is None:
            return False
        await self.db.delete(family)
        await self.db.flush()
        return True

    # ═════════════════════════════════════════════════════════════════════════
    # PipelineRun 제출 (Pipeline 기반 — 027 §4-3 Version Resolver)
    # ═════════════════════════════════════════════════════════════════════════

    async def submit_run_from_pipeline_version(
        self,
        pipeline_version_id: str,
        resolved_input_versions: dict[str, str],
    ) -> PipelineSubmitResponse:
        """
        `POST /pipeline-versions/{id}/runs` 구현 (v7.11). Version Resolver Modal 이
        확정한 `{split_id: version}` 을 받아 PipelineRun 1건을 생성하고 Celery dispatch.

        soft-deleted PipelineVersion 또는 모 Pipeline 은 차단.

        본 메서드는 §12-5 기준 "실행 시점" 에 해당하므로 validate_runtime 성격의
        최소 체크만 수행.
        """
        pipeline_version = await self.get_pipeline_version(pipeline_version_id)
        if pipeline_version is None:
            raise ValueError(f"PipelineVersion not found: {pipeline_version_id}")
        if not pipeline_version.is_active:
            raise ValueError(
                "PipelineVersion 이 비활성 상태라 새 run 을 제출할 수 없습니다."
            )
        pipeline = pipeline_version.pipeline
        if pipeline is None or not pipeline.is_active:
            raise ValueError(
                "모 Pipeline 이 비활성 상태라 새 run 을 제출할 수 없습니다."
            )

        # config 에서 PipelineConfig Pydantic 복원 (실행 파이프라인의 진짜 스펙)
        config = PipelineConfig(**pipeline_version.config)

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
        # 했는데 누락된 케이스 회복용. 매 실행 시 source 교집합을
        # 재계산해 빈 경우만 채운다.
        if not output_group.task_types:
            inferred_task_types = await self._intersect_source_task_types(config)
            if inferred_task_types:
                output_group.task_types = inferred_task_types
                logger.info(
                    "output 그룹 task_types 자동 백필",
                    group_id=output_group.id, task_types=inferred_task_types,
                )

        # 실행 시점 runtime 검증: resolved_input_versions 에 모든 source split 이 포함됐는지.
        expected_split_ids = set(config.get_all_source_split_ids())
        missing = expected_split_ids - set(resolved_input_versions.keys())
        if missing:
            raise ValueError(
                f"resolved_input_versions 에 다음 split_id 가 누락되었습니다: {sorted(missing)}"
            )

        # resolved_input_versions → 실행 시점의 dataset_version_id 매핑 (runtime 의미)
        runtime_dataset_ids = await self._resolve_versions_to_dataset_ids(
            resolved_input_versions
        )

        # output 버전 자동 증가 (manual 실행 = major++)
        version = await self._next_version(output_split_slot.id)
        logger.info(
            "Pipeline run 제출 시작",
            pipeline_id=pipeline.id, pipeline_name=pipeline.name,
            pipeline_version_id=pipeline_version.id,
            pipeline_version=pipeline_version.version,
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

        # PipelineRun 생성 — PipelineVersion.config 는 split_id 단위 spec 이므로 실행 시점에
        # source:dataset_split:<split_id> → source:dataset_version:<version_id> 로 치환한
        # resolved dict 를 transform_config 에 저장. Celery executor 는 이 resolved dict 의
        # dataset_version_id 단위로 데이터를 로드한다.
        resolved_config_dict = self._substitute_resolved_versions(
            pipeline_version.config, runtime_dataset_ids,
        )
        run = PipelineRun(
            id=str(uuid.uuid4()),
            pipeline_version_id=pipeline_version.id,
            automation_id=None,
            output_dataset_id=dataset.id,
            transform_config=resolved_config_dict,
            resolved_input_versions=resolved_input_versions,
            trigger_kind="manual_from_editor",
            status="PENDING",
        )
        self.db.add(run)
        await self.db.flush()

        # Celery dispatch — resolved dict (dataset_version_id 단위) 을 executor 에 전달
        from app.tasks.pipeline_tasks import run_pipeline
        celery_result = run_pipeline.delay(run.id, resolved_config_dict)
        run.celery_task_id = celery_result.id
        await self.db.flush()

        logger.info(
            "Pipeline run 디스패치 완료",
            pipeline_id=pipeline.id, pipeline_version_id=pipeline_version.id,
            run_id=run.id, celery_task_id=run.celery_task_id,
            input_versions=resolved_input_versions,
            runtime_dataset_ids=runtime_dataset_ids,
        )

        return PipelineSubmitResponse(
            execution_id=run.id,
            celery_task_id=run.celery_task_id,
            message="파이프라인 실행이 제출되었습니다.",
        )

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
