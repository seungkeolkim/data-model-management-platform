"""
cls_demote_head_to_single_label — Multi-label head 를 Single-label 로 강등하는 manipulator.

역할:
    지정 head 의 multi_label 플래그를 True → False 로 변경한다.
    cls_merge_classes 로 class 를 줄인 뒤 multi→single 전환에 사용.

    head_schema 변경:
      - 대상 head 의 multi_label 을 False 로 설정.

    labels 변경 (이미지별):
      - null(unknown) → null 유지. (§2-12 규약)
      - [class 1개] → 그대로 유지 (single-label 적합).
      - [] (explicit empty) → single-label 에서 허용 안 됨 → on_violation 정책에 따라 처리.
      - [class 2개 이상] → single-label 위반 → on_violation 정책에 따라 처리.

    on_violation 정책:
      - "skip": 위반 이미지를 결과에서 제외하고 로그에 경고 기록.
      - "fail": 즉시 ValueError 를 발생시켜 파이프라인 전체를 실패 처리.

    이미 single-label 인 head 를 지정하면 경고 로그 후 passthrough (에러 아님).

params:
    head_name:      str                — 강등 대상 head 이름 (필수).
    on_violation:   "skip" | "fail"    — single-label 위반 이미지 처리 정책 (필수, 기본 "fail").

이미지 바이너리 불변 → file_name 유지 → lazy copy.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)


class DemoteHeadToSingleLabelClassification(UnitManipulator):
    """DB seed name: "cls_demote_head_to_single_label"."""

    REQUIRED_PARAMS = ["head_name"]

    @property
    def name(self) -> str:
        return "cls_demote_head_to_single_label"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_demote_head_to_single_label 는 단일 입력만 지원합니다 (list 입력 불가)."
            )
        if input_meta.head_schema is None:
            raise ValueError(
                "cls_demote_head_to_single_label 는 classification DatasetMeta 에만 사용합니다 "
                "(head_schema 가 None 입니다)."
            )

        # ── params 파싱 ──
        target_head_name = params.get("head_name")
        if not isinstance(target_head_name, str) or not target_head_name.strip():
            raise ValueError(
                "head_name 이 비어있습니다. 강등 대상 Head 이름을 지정하세요."
            )
        target_head_name = target_head_name.strip()

        on_violation = params.get("on_violation", "fail")
        if on_violation not in ("skip", "fail"):
            raise ValueError(
                f"on_violation 은 'skip' 또는 'fail' 이어야 합니다: {on_violation!r}"
            )

        # ── 대상 head 찾기 ──
        target_head: HeadSchema | None = next(
            (head for head in input_meta.head_schema if head.name == target_head_name),
            None,
        )
        if target_head is None:
            existing_head_names = [head.name for head in input_meta.head_schema]
            raise ValueError(
                f"cls_demote_head_to_single_label: head_name='{target_head_name}' 가 "
                f"head_schema 에 없습니다. 존재하는 head: {existing_head_names}"
            )

        # 이미 single-label 이면 경고 후 passthrough.
        if not target_head.multi_label:
            logger.warning(
                "cls_demote_head_to_single_label: head '%s' 는 이미 single-label 입니다. "
                "변경 없이 passthrough 합니다.",
                target_head_name,
            )
            return _passthrough_copy(input_meta)

        # ── head_schema 재구성: 대상 head 의 multi_label → False ──
        new_head_schema = [
            HeadSchema(
                name=head.name,
                multi_label=False if head.name == target_head_name else head.multi_label,
                classes=list(head.classes),
            )
            for head in input_meta.head_schema
        ]

        # ── image_records 검증 + 변환 ──
        new_records: list[ImageRecord] = []
        skipped_count = 0

        for record in input_meta.image_records:
            source_labels = record.labels or {}
            head_label_value = source_labels.get(target_head_name)

            # null(unknown) → 그대로 통과. (§2-12: single-label 에서 null 허용)
            if head_label_value is None:
                new_records.append(_copy_record(record))
                continue

            # single-label 적합성 검사: null 또는 [class 1개]만 허용.
            label_count = len(head_label_value)

            if label_count == 1:
                # 정상: class 1개 — 그대로 유지.
                new_records.append(_copy_record(record))
                continue

            # 위반: [] (explicit empty) 또는 [class 2개 이상]
            violation_detail = (
                f"file_name={record.file_name}, head='{target_head_name}', "
                f"labels={head_label_value!r} (개수={label_count})"
            )

            if on_violation == "fail":
                raise ValueError(
                    f"cls_demote_head_to_single_label: single-label 위반 — "
                    f"{violation_detail}. "
                    f"on_violation='fail' 이므로 파이프라인을 중단합니다."
                )

            # on_violation == "skip": 경고 로그 후 해당 이미지 제외.
            logger.warning(
                "cls_demote_head_to_single_label: single-label 위반 이미지 skip — %s",
                violation_detail,
            )
            skipped_count += 1

        logger.info(
            "cls_demote_head_to_single_label 완료: head='%s' multi_label=True→False, "
            "총 %d장, 유지 %d장, skip %d장",
            target_head_name,
            len(input_meta.image_records),
            len(new_records),
            skipped_count,
        )

        return DatasetMeta(
            dataset_id=input_meta.dataset_id,
            storage_uri=input_meta.storage_uri,
            categories=[],
            image_records=new_records,
            head_schema=new_head_schema,
            extra=dict(input_meta.extra) if input_meta.extra else {},
        )


# ─────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────


def _copy_record(record: ImageRecord) -> ImageRecord:
    """ImageRecord 얕은 복제. labels dict 과 list 값을 새 객체로 만든다."""
    new_labels: dict[str, list[str] | None] = {
        head_name: (list(class_names) if class_names is not None else None)
        for head_name, class_names in (record.labels or {}).items()
    }
    return replace(
        record,
        labels=new_labels,
        extra=dict(record.extra) if record.extra else {},
    )


def _passthrough_copy(input_meta: DatasetMeta) -> DatasetMeta:
    """입력을 변경 없이 얕은 복제한다. 이미 single-label 인 head 지정 시 사용."""
    new_head_schema = [
        HeadSchema(
            name=head.name,
            multi_label=head.multi_label,
            classes=list(head.classes),
        )
        for head in (input_meta.head_schema or [])
    ]
    new_records = [_copy_record(record) for record in input_meta.image_records]
    return DatasetMeta(
        dataset_id=input_meta.dataset_id,
        storage_uri=input_meta.storage_uri,
        categories=[],
        image_records=new_records,
        head_schema=new_head_schema,
        extra=dict(input_meta.extra) if input_meta.extra else {},
    )
