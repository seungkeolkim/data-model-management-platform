"""
merge_datasets Manipulator.

복수의 DatasetMeta를 하나로 병합한다.
POST_MERGE scope 전용 — list[DatasetMeta]를 입력받아 단일 DatasetMeta를 반환.

통일포맷:
  - categories는 list[str] (name 기반). ID 리매핑 불필요.
  - annotation.category_name은 그대로 보존.
  - 포맷 검증 없음 (통일포맷이므로 cross-format merge 가능).

핵심 처리:
  1. 파일명 충돌 감지 → 충돌 파일만 prefix 적용 ({dataset_name}_{4자리hash}_{원본파일명})
  2. 카테고리 통합 — name 기반 union (등장 순서 보존)
  3. 이미지 레코드 병합 — image_id 순차 재번호, 출처 정보(extra) 보존
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import Annotation, DatasetMeta, ImageRecord

logger = logging.getLogger(__name__)


class MergeDatasets(UnitManipulator):
    """
    복수 소스 데이터셋 병합 Manipulator.

    accepts_multi_input = True 로 표시하여 DAG executor가
    _merge_metas()를 건너뛰고 list[DatasetMeta]를 직접 전달하도록 한다.

    DB seed name: "merge_datasets"
    """

    accepts_multi_input: bool = True

    @property
    def name(self) -> str:
        return "merge_datasets"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        복수 DatasetMeta를 하나로 병합한다.

        통일포맷이므로 category_id 리매핑은 불필요.
        categories는 name union, annotations의 category_name은 그대로 보존.

        Args:
            input_meta: list[DatasetMeta] (2개 이상 필수)
            params: 현재 사용하지 않음 (향후 확장용)
            context: 실행 컨텍스트 (선택)

        Returns:
            병합된 DatasetMeta.
            extra에 file_name_mapping (rename된 파일만)과 source_dataset_ids를 포함.
            각 ImageRecord.extra에 source_dataset_id, source_storage_uri, original_file_name 포함.

        Raises:
            TypeError: input_meta가 list가 아닐 때
            ValueError: 소스가 2개 미만일 때
        """
        if not isinstance(input_meta, list):
            raise TypeError(
                "merge_datasets는 list[DatasetMeta]를 입력받아야 합니다. "
                f"받은 타입: {type(input_meta).__name__}"
            )
        if len(input_meta) < 2:
            raise ValueError(
                f"merge_datasets는 2개 이상의 소스가 필요합니다. "
                f"받은 소스 수: {len(input_meta)}"
            )

        # ── 소스별 hash 계산 (dataset_id 기반, 한 번만) ──
        dataset_hash_table = _build_dataset_hash_table(input_meta)

        # ── 파일명 충돌 감지 ──
        colliding_file_names = _detect_file_name_collisions(input_meta)

        if colliding_file_names:
            logger.info(
                "파일명 충돌 감지: %d개 파일명이 2개 이상의 소스에 존재",
                len(colliding_file_names),
            )

        # ── 카테고리 통합 (name union, 등장 순서 보존) ──
        unified_categories: list[str] = list(
            dict.fromkeys(name for meta in input_meta for name in meta.categories)
        )

        # ── 이미지 레코드 병합 ──
        merged_records: list[ImageRecord] = []
        file_name_mapping: dict[str, dict[str, str]] = {}
        image_id_counter = 1

        for meta in input_meta:
            dataset_id = meta.dataset_id
            dataset_display_name, dataset_hash = dataset_hash_table[dataset_id]

            for record in meta.image_records:
                original_file_name = record.file_name

                # 충돌 파일만 prefix 적용
                if original_file_name in colliding_file_names:
                    new_file_name = (
                        f"{dataset_display_name}_{dataset_hash}_{original_file_name}"
                    )
                    file_name_mapping.setdefault(dataset_id, {})[
                        original_file_name
                    ] = new_file_name
                else:
                    new_file_name = original_file_name

                # 출처 정보를 extra에 저장 (모든 레코드, rename 여부 무관)
                merged_extra = {
                    **record.extra,
                    "source_dataset_id": dataset_id,
                    "source_storage_uri": meta.storage_uri,
                    "original_file_name": original_file_name,
                }

                # annotation은 그대로 복사 (통일포맷이므로 category_name 리매핑 불필요)
                merged_records.append(
                    ImageRecord(
                        image_id=image_id_counter,
                        file_name=new_file_name,
                        width=record.width,
                        height=record.height,
                        annotations=list(record.annotations),
                        extra=merged_extra,
                    )
                )
                image_id_counter += 1

        logger.info(
            "데이터셋 병합 완료: 소스 %d개, 총 이미지 %d장, 카테고리 %d개, rename %d건",
            len(input_meta),
            len(merged_records),
            len(unified_categories),
            sum(len(v) for v in file_name_mapping.values()),
        )

        return DatasetMeta(
            dataset_id="",
            storage_uri="",
            categories=unified_categories,
            image_records=merged_records,
            extra={
                "file_name_mapping": file_name_mapping,
                "source_dataset_ids": [m.dataset_id for m in input_meta],
            },
        )


# ─────────────────────────────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────────────────────────────


def _build_dataset_hash_table(
    metas: list[DatasetMeta],
) -> dict[str, tuple[str, str]]:
    """
    소스별 (표시용 이름, 4자리 hash) 테이블을 생성한다.

    Returns:
        {dataset_id: (display_name, hash_4char)}
    """
    table: dict[str, tuple[str, str]] = {}
    for meta in metas:
        display_name = meta.extra.get("dataset_name", meta.dataset_id[:8])
        hash_4char = hashlib.md5(meta.dataset_id.encode()).hexdigest()[:4]
        table[meta.dataset_id] = (display_name, hash_4char)
    return table


def _detect_file_name_collisions(
    metas: list[DatasetMeta],
) -> set[str]:
    """
    전체 소스에서 file_name을 수집하여 충돌(2개 이상의 소스에 존재)하는 파일명을 반환한다.
    """
    file_name_sources: dict[str, set[str]] = {}
    for meta in metas:
        for record in meta.image_records:
            file_name_sources.setdefault(record.file_name, set()).add(
                meta.dataset_id
            )

    return {
        file_name
        for file_name, sources in file_name_sources.items()
        if len(sources) > 1
    }
