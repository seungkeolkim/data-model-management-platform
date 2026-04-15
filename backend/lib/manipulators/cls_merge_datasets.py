"""
cls_merge_datasets — 복수 Classification 데이터셋 병합 manipulator (STUB).

역할:
    여러 classification DatasetMeta (head_schema + labels + SHA 기반 images/{sha}.{ext}) 를
    하나의 통합 DatasetMeta 로 병합한다. Detection 용 `merge_datasets` 와는 자료구조가
    이질적이어서 별도 manipulator 로 분리한다 (merge_datasets 는 categories/annotations 기반).

주요 고려사항 (실제 구현 시):
    1. head_schema 정합성 검증
       - 동일 head 이름은 multi_label 값이 동일해야 함.
       - 동일 head 의 classes 는 prefix 보존 원칙(기존 순서 변경/삭제 금지). 신규 class 는 append.
       - 이름 충돌이 있으면 호출자가 cls_rename_head / cls_rename_class 으로
         사전 정리해야 한다. 이 manipulator 는 충돌 시 명시적 에러.
    2. 이미지 dedup
       - 동일 SHA 가 여러 소스에 등장하면 1개만 유지. labels 는 (head 별) union (multi_label=true)
         또는 single-label 충돌 시 정책 결정 필요 (FAIL/SKIP — ingest 와 동일 규약 고려).
    3. ImageRecord.extra.source_storage_uri 전파
       - 후속 Phase B 가 src_uri 를 결정할 때 어느 소스에서 왔는지 추적.

params:
    on_single_label_conflict: "FAIL" | "SKIP" — 기본 "FAIL".
    (추후 확정)

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class MergeDatasetsClassification(UnitManipulator):
    """DB seed name: "cls_merge_datasets"."""

    @property
    def name(self) -> str:
        return "cls_merge_datasets"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "cls_merge_datasets 는 아직 구현되지 않았습니다 (stub)."
        )
