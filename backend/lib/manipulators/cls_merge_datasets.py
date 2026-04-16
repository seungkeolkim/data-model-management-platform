"""
cls_merge_datasets — 복수 Classification DatasetMeta 병합 manipulator.

정책 문서: `objective_n_plan_7th.md §2-11`.

역할:
    SHA-1 기반 동일 이미지 dedup, head_schema 통합, label 충돌 처리를 포함해
    N 개의 classification DatasetMeta 를 단일 결과로 병합한다. Detection 용
    `det_merge_datasets` 와는 자료구조가 달라 분리돼 있다 (categories/annotations
    vs head_schema/labels).

Params (`cls_merge_compat.resolve_merge_params` 로 검증):
    on_head_mismatch:      "error" (default) | "fill_empty"
    on_class_set_mismatch: "error" (default) | "multi_label_union"
    on_label_conflict:     "drop_image" (default) | "merge_if_compatible"

입력 호환성 (head/class 스키마) 은 `cls_merge_compat.check_merge_schema_compatibility`
를 재사용한다 — FE 정적 검증 (pipeline_service) 도 동일 함수를 호출하므로 규칙
drift 가 발생하지 않는다. 본 manipulator 는 최종 안전망으로 실행 진입부에서 해당
검증을 다시 수행해 ValueError 로 실패시킨다.

라벨 충돌 판정 규칙 (`on_label_conflict=merge_if_compatible`):
    - single_label head: 값이 다르면 **무조건 폐기**.
    - multi_label head: 각 class 를 "pos / explicit_neg / unknown" 3값으로 판정해
      pos ↔ explicit_neg 상충이 있으면 폐기, 아니면 union.
      explicit_neg = "해당 입력의 원본 classes 에 그 class 가 있었는데 labels 에 없음".
      unknown      = "해당 입력의 원본 classes 에 그 class 가 애초에 없음".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from lib.pipeline.cls_merge_compat import (
    CLASS_SET_MISMATCH_MULTI_LABEL_UNION,
    HEAD_MISMATCH_FILL_EMPTY,
    LABEL_CONFLICT_MERGE_IF_COMPATIBLE,
    OPTION_ON_CLASS_SET_MISMATCH,
    OPTION_ON_HEAD_MISMATCH,
    OPTION_ON_LABEL_CONFLICT,
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
    건너뛰고 list[DatasetMeta] 를 직접 전달하도록 한다. detection 의
    det_merge_datasets 에 대응되는 classification 측 병합 노드.

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
        on_label_conflict = resolved_params[OPTION_ON_LABEL_CONFLICT]

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

        # ── Image record 병합: SHA dedup + file_name rename + label 충돌 처리 ──
        merged_records, rename_log, drop_log = self._merge_image_records(
            input_metas,
            merged_head_schema=merged_head_schema,
            on_label_conflict=on_label_conflict,
        )

        # ── 요약 로그 (processing.log 에 자동 포함) ──
        if promoted_head_names:
            logger.info(
                "cls_merge_datasets: multi_label_union 으로 승격된 head=%s",
                sorted(promoted_head_names),
            )
        for rename_entry in rename_log:
            logger.info(
                "cls_merge_datasets rename: source_dataset_id=%s sha=%s %s -> %s",
                rename_entry["source_dataset_id"],
                rename_entry["sha"],
                rename_entry["original"],
                rename_entry["renamed"],
            )
        for drop_entry in drop_log:
            logger.warning(
                "cls_merge_datasets drop: sha=%s reason=%s sources=%s",
                drop_entry["sha"],
                drop_entry["reason"],
                drop_entry["sources"],
            )
        logger.info(
            "cls_merge_datasets: dropped=%d, renamed=%d, promoted=%d heads, "
            "result_images=%d, result_heads=%d",
            len(drop_log),
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
            (fill_empty 옵션이 아닌 상태에서 새 head 가 들어오면 정적 검증에서 이미 error 로 잡혀야
            하지만 런타임 방어를 위해 union 로직 자체는 동일하게 동작시킨다.)

        Class union 도 동일 규약. multi_label_union 옵션이면 multi_label 플래그를 True 로 승격.
        """
        # head_name → 병합 중인 HeadSchema
        # (classes 는 리스트로 관리하며 최종적으로 list[str] 로 확정).
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
        on_label_conflict: str,
    ) -> tuple[list[ImageRecord], list[dict[str, Any]], list[dict[str, Any]]]:
        """
        SHA dedup + label 병합 + file_name 충돌 rename.

        반환:
            (merged_records, rename_log, drop_log)
        """
        merged_head_names = [head.name for head in merged_head_schema]
        head_is_multi: dict[str, bool] = {
            head.name: head.multi_label for head in merged_head_schema
        }
        # 각 입력별 per-head 의 "원본 classes 집합" — explicit_neg 판정에 사용.
        # input_index → head_name → set[class_name]
        original_classes_per_input: list[dict[str, set[str]]] = []
        for meta in input_metas:
            assert meta.head_schema is not None
            original_classes_per_input.append(
                {head.name: set(head.classes) for head in meta.head_schema}
            )

        # SHA 별로 모든 입력에서의 등장 정보 누적.
        occurrences_by_sha: dict[str, list[dict[str, Any]]] = {}
        for input_index, meta in enumerate(input_metas):
            for record in meta.image_records:
                if not record.sha:
                    # classification 데이터는 sha 가 반드시 세팅돼 있어야 한다 (manifest_io 보장).
                    raise ValueError(
                        f"cls_merge_datasets: 입력 #{input_index + 1} 의 image_record "
                        f"에 sha 가 없습니다 (file_name={record.file_name})."
                    )
                occurrences_by_sha.setdefault(record.sha, []).append(
                    {
                        "input_index": input_index,
                        "record": record,
                        "source_dataset_id": meta.dataset_id,
                    }
                )

        # 결과 레코드 구성.
        merged_records: list[ImageRecord] = []
        rename_log: list[dict[str, Any]] = []
        drop_log: list[dict[str, Any]] = []
        used_file_names: set[str] = set()

        for sha, occurrences in occurrences_by_sha.items():
            if len(occurrences) == 1:
                # 단일 소스: 라벨 병합 불필요, head 누락만 빈 리스트로 채움.
                only = occurrences[0]
                record = only["record"]
                merged_labels = _align_labels_to_merged_heads(
                    record.labels or {}, merged_head_names
                )
                file_name = _reserve_file_name(record.file_name, used_file_names)
                if file_name != record.file_name:
                    rename_log.append({
                        "sha": sha,
                        "source_dataset_id": only["source_dataset_id"],
                        "original": record.file_name,
                        "renamed": file_name,
                    })
                merged_records.append(
                    ImageRecord(
                        image_id=record.image_id,
                        file_name=file_name,
                        width=record.width,
                        height=record.height,
                        sha=sha,
                        labels=merged_labels,
                        extra=dict(record.extra) if record.extra else {},
                    )
                )
                continue

            # 복수 소스 — 라벨 충돌 판정.
            merge_outcome = _resolve_label_conflict(
                occurrences=occurrences,
                merged_head_schema=merged_head_schema,
                head_is_multi=head_is_multi,
                original_classes_per_input=original_classes_per_input,
                on_label_conflict=on_label_conflict,
            )
            if merge_outcome.dropped:
                drop_log.append({
                    "sha": sha,
                    "reason": merge_outcome.drop_reason,
                    "sources": [
                        {
                            "dataset_id": occ["source_dataset_id"],
                            "labels": dict(occ["record"].labels or {}),
                        }
                        for occ in occurrences
                    ],
                })
                continue

            # 대표 레코드: 첫 occurrence 의 width/height/file_name 사용 (결정론).
            primary = occurrences[0]
            primary_record = primary["record"]
            file_name = _reserve_file_name(primary_record.file_name, used_file_names)
            if file_name != primary_record.file_name:
                rename_log.append({
                    "sha": sha,
                    "source_dataset_id": primary["source_dataset_id"],
                    "original": primary_record.file_name,
                    "renamed": file_name,
                })
            merged_records.append(
                ImageRecord(
                    image_id=primary_record.image_id,
                    file_name=file_name,
                    width=primary_record.width,
                    height=primary_record.height,
                    sha=sha,
                    labels=merge_outcome.merged_labels,
                    extra=dict(primary_record.extra) if primary_record.extra else {},
                )
            )

        return merged_records, rename_log, drop_log


# =============================================================================
# 모듈 레벨 헬퍼 (클래스 외부, 테스트 용이)
# =============================================================================


@dataclass
class _MergeOutcome:
    dropped: bool
    drop_reason: str
    merged_labels: dict[str, list[str]]


def _align_labels_to_merged_heads(
    source_labels: dict[str, list[str]],
    merged_head_names: list[str],
) -> dict[str, list[str]]:
    """
    단일 소스의 라벨을 최종 head 순서에 맞춰 정렬하고, 누락된 head 는 빈 리스트로 채운다.
    fill_empty 옵션 적용 결과에 해당.
    """
    result: dict[str, list[str]] = {}
    for head_name in merged_head_names:
        result[head_name] = list(source_labels.get(head_name, []))
    return result


def _reserve_file_name(original: str, used: set[str]) -> str:
    """
    file_name 충돌 시 suffix 부여. SHA dedup 통과한 레코드끼리 서로 다른 SHA 인데 file_name 이
    겹치는 경우에만 호출된다. "{stem}_{n}{ext}" 형식으로 1부터 증가.
    """
    if original not in used:
        used.add(original)
        return original

    # 확장자 분리 (경로 컴포넌트까지 고려).
    from pathlib import PurePosixPath

    path_obj = PurePosixPath(original)
    stem = path_obj.stem
    suffix = path_obj.suffix
    parent = str(path_obj.parent) if str(path_obj.parent) != "." else ""

    counter = 1
    while True:
        candidate_name = f"{stem}_{counter}{suffix}"
        candidate = f"{parent}/{candidate_name}" if parent else candidate_name
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def _resolve_label_conflict(
    occurrences: list[dict[str, Any]],
    merged_head_schema: list[HeadSchema],
    head_is_multi: dict[str, bool],
    original_classes_per_input: list[dict[str, set[str]]],
    on_label_conflict: str,
) -> _MergeOutcome:
    """
    동일 SHA 에 여러 occurrence 가 있을 때 각 head 별로 라벨을 병합한다.

    규칙은 §2-11-5 참고.
    """
    drop_image_mode = on_label_conflict != LABEL_CONFLICT_MERGE_IF_COMPATIBLE

    merged_labels: dict[str, list[str]] = {}
    for head in merged_head_schema:
        head_name = head.name
        is_multi = head_is_multi[head_name]

        # 각 occurrence 가 해당 head 에 대해 가진 labels 수집.
        per_input_labels: list[tuple[int, list[str]]] = []
        for occ in occurrences:
            record_labels = occ["record"].labels or {}
            per_input_labels.append(
                (occ["input_index"], list(record_labels.get(head_name, [])))
            )

        # head 가 해당 입력의 원본 schema 에 없었던 경우 → unknown 취급.
        # 라벨이 모두 동일하면 그냥 그 값 사용.
        distinct_label_sets = {tuple(sorted(labels)) for _, labels in per_input_labels}
        if len(distinct_label_sets) == 1:
            merged_labels[head_name] = list(per_input_labels[0][1])
            continue

        # 라벨이 occurrence 별로 다름 → 충돌.
        if drop_image_mode:
            return _MergeOutcome(
                dropped=True,
                drop_reason=f"label_conflict(head={head_name})",
                merged_labels={},
            )

        # merge_if_compatible 모드.
        if not is_multi:
            # single-label head: 값 다르면 무조건 폐기.
            return _MergeOutcome(
                dropped=True,
                drop_reason=f"single_label_mismatch(head={head_name})",
                merged_labels={},
            )

        # multi-label head — 각 class 별로 pos/explicit_neg/unknown 판정.
        # union candidate: 모든 occurrence 의 라벨에 등장한 class 들.
        union_classes: list[str] = []
        seen = set()
        for _, labels in per_input_labels:
            for cls_name in labels:
                if cls_name not in seen:
                    seen.add(cls_name)
                    union_classes.append(cls_name)

        conflict_detected = False
        for candidate_class in union_classes:
            # 각 입력에서 이 class 가 어떤 상태였는지 확인.
            for input_index, labels in per_input_labels:
                original_classes = original_classes_per_input[input_index].get(head_name)
                if original_classes is None:
                    # head 자체가 이 입력에 없었음 — unknown.
                    continue
                if candidate_class in labels:
                    continue  # pos
                if candidate_class in original_classes:
                    # 이 입력의 원본 classes 에 있었는데 라벨에 없음 → explicit_neg.
                    # 다른 입력에서는 pos 이므로 pos ↔ explicit_neg 상충.
                    conflict_detected = True
                    break
                # else: unknown — 허용.
            if conflict_detected:
                break

        if conflict_detected:
            return _MergeOutcome(
                dropped=True,
                drop_reason=f"multi_label_pos_neg_conflict(head={head_name})",
                merged_labels={},
            )

        # 통과 — union 을 결과로.
        merged_labels[head_name] = union_classes

    return _MergeOutcome(dropped=False, drop_reason="", merged_labels=merged_labels)
