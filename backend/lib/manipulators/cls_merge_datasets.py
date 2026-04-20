"""
cls_merge_datasets — 복수 Classification DatasetMeta 병합 manipulator.

정책 문서: `objective_n_plan_7th.md §2-11` + §2-8 (filename identity 확정본).

역할:
    N 개의 classification DatasetMeta 를 단일 결과로 병합한다. 이미지 identity 는
    filename 기반이며, 동일 파일명이 여러 입력에 존재하면 detection 의
    `det_merge_datasets` 와 동일한 prefix rename 정책으로 공존시킨다.

Params (`cls_merge_compat.resolve_merge_params` 로 검증):
    on_head_mismatch:      "error" (default) | "fill_empty"
    on_class_set_mismatch: "error" (default) | "multi_label_union"

입력 호환성 (head/class 스키마) 은 `cls_merge_compat.check_merge_schema_compatibility`
를 재사용한다 — FE 정적 검증 (pipeline_service) 도 동일 함수를 호출하므로 규칙
drift 가 발생하지 않는다. 본 manipulator 는 최종 안전망으로 실행 진입부에서 해당
검증을 다시 수행해 ValueError 로 실패시킨다.

이미지 처리 규칙 (§2-8 filename identity 확정):
    - 과거의 SHA 기반 content dedup 은 폐지. 같은 파일명이라도 서로 다른 입력에서
      왔다면 별개 이미지로 취급해 결과에 모두 포함한다.
    - 파일명 충돌(2개 이상 입력에 같은 파일명 존재) → detection 과 동일하게
      `{display_name}_{md5_4자리}_{original_filename}` prefix 를 부착해 분리.
    - Phase B 이미지 실체화는 `record.extra.source_storage_uri` + `original_file_name`
      으로 소스 경로를 확정하므로, merge 단계에서 이 2개 extra 키를 반드시 세팅한다.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import PurePosixPath
from typing import Any

from lib.pipeline.cls_merge_compat import (
    CLASS_SET_MISMATCH_MULTI_LABEL_UNION,
    HEAD_MISMATCH_FILL_EMPTY,
    OPTION_ON_CLASS_SET_MISMATCH,
    OPTION_ON_HEAD_MISMATCH,
    check_merge_schema_compatibility,
    resolve_merge_params,
)
from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)


class MergeDatasetsClassification(UnitManipulator):
    """
    복수 Classification 소스 데이터셋 병합 Manipulator.

    accepts_multi_input = True 로 표시하여 DAG executor 가 _merge_metas() 를
    건너뛰고 list[DatasetMeta] 를 직접 전달하도록 한다.

    DB seed name: "cls_merge_datasets"
    """

    accepts_multi_input: bool = True

    @property
    def name(self) -> str:
        return "cls_merge_datasets"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        input_metas = self._normalize_inputs(input_meta)
        resolved_params = resolve_merge_params(params)
        on_head_mismatch = resolved_params[OPTION_ON_HEAD_MISMATCH]
        on_class_set_mismatch = resolved_params[OPTION_ON_CLASS_SET_MISMATCH]

        # ── 최종 안전망: 입력 호환성 재검증 (FE/pipeline_service 가 이미 걸러도 API 우회 대비) ──
        issues = check_merge_schema_compatibility(
            [meta.head_schema for meta in input_metas],
            params,
        )
        if issues:
            joined_messages = "\n".join(f"[{issue.code}] {issue.message}" for issue in issues)
            raise ValueError(
                f"cls_merge_datasets 입력 호환성 검증 실패:\n{joined_messages}"
            )

        # ── Head union 결정 ──
        merged_head_schema, promoted_head_names = self._merge_head_schemas(
            input_metas,
            on_head_mismatch=on_head_mismatch,
            on_class_set_mismatch=on_class_set_mismatch,
        )

        # ── Image record 병합: 모든 입력의 레코드 유지 + filename 충돌 rename ──
        merged_records, rename_log = self._merge_image_records(
            input_metas,
            merged_head_schema=merged_head_schema,
        )

        # ── 요약 로그 (processing.log 에 자동 포함) ──
        if promoted_head_names:
            logger.info(
                "cls_merge_datasets: multi_label_union 으로 승격된 head=%s",
                sorted(promoted_head_names),
            )
        for rename_entry in rename_log:
            logger.info(
                "cls_merge_datasets rename: source_dataset_id=%s %s -> %s",
                rename_entry["source_dataset_id"],
                rename_entry["original"],
                rename_entry["renamed"],
            )
        logger.info(
            "cls_merge_datasets: renamed=%d, promoted=%d heads, "
            "result_images=%d, result_heads=%d",
            len(rename_log),
            len(promoted_head_names),
            len(merged_records),
            len(merged_head_schema),
        )

        # 결과 DatasetMeta — dataset_id/storage_uri 는 후행 executor 가 덮어쓴다.
        return DatasetMeta(
            dataset_id=input_metas[0].dataset_id,
            storage_uri=input_metas[0].storage_uri,
            categories=[],
            image_records=merged_records,
            head_schema=merged_head_schema,
            extra={},
        )

    # -------------------------------------------------------------------------
    # 입력 정규화
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalize_inputs(
        input_meta: DatasetMeta | list[DatasetMeta],
    ) -> list[DatasetMeta]:
        if isinstance(input_meta, DatasetMeta):
            raise TypeError(
                "cls_merge_datasets 는 multi-input 전용입니다 (accepts_multi_input=True). "
                "단일 DatasetMeta 가 들어왔습니다."
            )
        if not isinstance(input_meta, list):
            type_name = type(input_meta).__name__
            raise TypeError(
                f"cls_merge_datasets 는 list[DatasetMeta] 를 받아야 합니다: {type_name}"
            )
        if len(input_meta) < 2:
            raise ValueError(
                f"cls_merge_datasets 는 최소 2개 이상의 입력이 필요합니다: {len(input_meta)}개"
            )
        for index, meta in enumerate(input_meta):
            if not isinstance(meta, DatasetMeta):
                raise TypeError(
                    f"입력 #{index + 1} 이 DatasetMeta 가 아닙니다: {type(meta).__name__}"
                )
            if meta.head_schema is None:
                raise ValueError(
                    f"입력 #{index + 1} 의 head_schema 가 None 입니다. "
                    "cls_merge_datasets 는 classification 데이터셋만 병합합니다."
                )
        return input_meta

    # -------------------------------------------------------------------------
    # Head / class union
    # -------------------------------------------------------------------------

    @staticmethod
    def _merge_head_schemas(
        input_metas: list[DatasetMeta],
        on_head_mismatch: str,
        on_class_set_mismatch: str,
    ) -> tuple[list[HeadSchema], set[str]]:
        """
        각 입력의 head_schema 를 규약(§2-11-3/4/7)대로 통합한다.

        순서:
            1) 입력 #1 의 head 순서를 시작점으로.
            2) 이후 입력에서 새로 등장한 head 는 입력 순서 + head 등장 순서대로 append.

        Class union 도 동일 규약. multi_label_union 옵션이면 multi_label 플래그를 True 로 승격.
        """
        merged_by_name: dict[str, dict[str, Any]] = {}
        head_order: list[str] = []
        promoted_head_names: set[str] = set()

        for meta in input_metas:
            assert meta.head_schema is not None  # _normalize_inputs 가 보장
            for head in meta.head_schema:
                if head.name not in merged_by_name:
                    # 신규 head — 최초 등장 입력의 설정을 그대로 받아 시작.
                    merged_by_name[head.name] = {
                        "multi_label": head.multi_label,
                        "classes_order": list(head.classes),
                        "classes_set": set(head.classes),
                    }
                    head_order.append(head.name)
                    continue

                # 기존 head — class union 수행. 필요 시 multi_label 승격.
                slot = merged_by_name[head.name]
                existing_classes_set = slot["classes_set"]
                new_classes = [cls for cls in head.classes if cls not in existing_classes_set]
                if new_classes:
                    if on_class_set_mismatch != CLASS_SET_MISMATCH_MULTI_LABEL_UNION:
                        # 정적 검증이 이미 막아야 할 상황이지만 런타임 방어.
                        raise ValueError(
                            f"cls_merge_datasets: head '{head.name}' 의 class 집합 불일치를 "
                            f"병합하려면 on_class_set_mismatch=multi_label_union 옵션이 "
                            f"필요합니다. 누락된 class={new_classes}"
                        )
                    slot["classes_order"].extend(new_classes)
                    slot["classes_set"].update(new_classes)
                    slot["multi_label"] = True
                    promoted_head_names.add(head.name)
                # 승격 옵션이 켜져 있고 플래그만 다른 경우에도 강제 multi 로.
                if (
                    on_class_set_mismatch == CLASS_SET_MISMATCH_MULTI_LABEL_UNION
                    and not slot["multi_label"]
                    and head.multi_label
                ):
                    slot["multi_label"] = True
                    promoted_head_names.add(head.name)

        # fill_empty 옵션이 꺼진 상태에서 head 집합 불일치가 런타임에 발견되면 방어.
        head_name_sets = [{head.name for head in meta.head_schema or []} for meta in input_metas]
        union_names = set().union(*head_name_sets)
        if on_head_mismatch != HEAD_MISMATCH_FILL_EMPTY and any(
            names != union_names for names in head_name_sets
        ):
            raise ValueError(
                "cls_merge_datasets: head 집합 불일치를 병합하려면 "
                "on_head_mismatch=fill_empty 옵션이 필요합니다."
            )

        merged_head_schema = [
            HeadSchema(
                name=name,
                multi_label=bool(merged_by_name[name]["multi_label"]),
                classes=list(merged_by_name[name]["classes_order"]),
            )
            for name in head_order
        ]
        return merged_head_schema, promoted_head_names

    # -------------------------------------------------------------------------
    # Image record 병합
    # -------------------------------------------------------------------------

    @staticmethod
    def _merge_image_records(
        input_metas: list[DatasetMeta],
        merged_head_schema: list[HeadSchema],
    ) -> tuple[list[ImageRecord], list[dict[str, Any]]]:
        """
        모든 입력의 image_records 를 순서대로 결합한다. SHA dedup 은 수행하지 않고,
        file_name 이 여러 입력에 걸쳐 충돌하는 경우에만 detection 스타일 prefix 를
        부착해 공존시킨다.

        Returns:
            (merged_records, rename_log)
        """
        merged_head_names = [head.name for head in merged_head_schema]

        # ── 소스별 (display_name, 4자리 hash) 테이블 ── (detection 과 동일 규칙)
        dataset_hash_table = _build_dataset_hash_table(input_metas)

        # ── 파일명 충돌 감지 ── 2개 이상 입력에서 등장한 file_name 집합
        colliding_file_names = _detect_file_name_collisions(input_metas)
        if colliding_file_names:
            logger.info(
                "cls_merge_datasets: 파일명 충돌 감지 — %d 개 파일명이 2개 이상 입력에 존재",
                len(colliding_file_names),
            )

        merged_records: list[ImageRecord] = []
        rename_log: list[dict[str, Any]] = []
        image_id_counter = 1

        for meta in input_metas:
            dataset_id = meta.dataset_id
            dataset_display_name, dataset_hash_4 = dataset_hash_table[dataset_id]

            for record in meta.image_records:
                original_file_name = record.file_name

                # 충돌 파일만 prefix 부여. classification 의 file_name 은 "images/xxx.jpg"
                # 형태이므로 basename 부분만 prefix 를 부착해 "images/" 경로는 유지한다.
                if original_file_name in colliding_file_names:
                    new_file_name = _apply_rename_prefix(
                        original_file_name=original_file_name,
                        display_name=dataset_display_name,
                        hash_4=dataset_hash_4,
                    )
                    rename_log.append({
                        "source_dataset_id": dataset_id,
                        "original": original_file_name,
                        "renamed": new_file_name,
                    })
                else:
                    new_file_name = original_file_name

                # Phase B 이미지 실체화가 소스 경로를 재구성할 수 있도록 extra 에 출처를 남긴다.
                merged_extra = dict(record.extra) if record.extra else {}
                merged_extra["source_dataset_id"] = dataset_id
                merged_extra["source_storage_uri"] = meta.storage_uri
                merged_extra["original_file_name"] = original_file_name

                merged_labels = _align_labels_to_merged_heads(
                    record.labels or {}, merged_head_names
                )

                merged_records.append(
                    ImageRecord(
                        image_id=image_id_counter,
                        file_name=new_file_name,
                        width=record.width,
                        height=record.height,
                        labels=merged_labels,
                        extra=merged_extra,
                    )
                )
                image_id_counter += 1

        return merged_records, rename_log


# =============================================================================
# 모듈 레벨 헬퍼 (클래스 외부, 테스트 용이)
# =============================================================================


def _align_labels_to_merged_heads(
    source_labels: dict[str, list[str] | None],
    merged_head_names: list[str],
) -> dict[str, list[str] | None]:
    """
    단일 소스의 라벨을 최종 head 순서에 맞춰 정렬하고, 누락된 head 는 None(unknown) 으로 채운다.
    fill_empty 옵션 적용 결과에 해당. §2-12 확정 규약.
    """
    result: dict[str, list[str] | None] = {}
    for head_name in merged_head_names:
        if head_name in source_labels:
            value = source_labels[head_name]
            result[head_name] = list(value) if value is not None else None
        else:
            result[head_name] = None
    return result


def _build_dataset_hash_table(
    metas: list[DatasetMeta],
) -> dict[str, tuple[str, str]]:
    """
    소스별 (표시용 이름, 4자리 hash) 테이블을 생성한다. detection 과 동일 규칙.
    """
    table: dict[str, tuple[str, str]] = {}
    for meta in metas:
        display_name = (meta.extra or {}).get("dataset_name", meta.dataset_id[:8])
        hash_4char = hashlib.md5(meta.dataset_id.encode()).hexdigest()[:4]
        table[meta.dataset_id] = (display_name, hash_4char)
    return table


def _detect_file_name_collisions(
    metas: list[DatasetMeta],
) -> set[str]:
    """
    전체 입력에서 file_name 을 수집해, 2개 이상 서로 다른 소스에 존재하는 파일명을 반환한다.
    같은 소스 내부 중복은 filesystem 상 불가능하므로 무시한다.
    """
    file_name_sources: dict[str, set[str]] = {}
    for meta in metas:
        for record in meta.image_records:
            file_name_sources.setdefault(record.file_name, set()).add(meta.dataset_id)
    return {
        file_name
        for file_name, sources in file_name_sources.items()
        if len(sources) > 1
    }


def _apply_rename_prefix(
    *,
    original_file_name: str,
    display_name: str,
    hash_4: str,
) -> str:
    """
    `images/xxx.jpg` → `images/{display_name}_{hash_4}_xxx.jpg` 형태로 rename.
    basename 이 있는 경로 컴포넌트는 유지하며 basename 에만 prefix 를 부착한다.
    """
    path_obj = PurePosixPath(original_file_name)
    new_basename = f"{display_name}_{hash_4}_{path_obj.name}"
    parent = str(path_obj.parent)
    if parent and parent != ".":
        return f"{parent}/{new_basename}"
    return new_basename
